import hashlib
import hmac
import ipaddress
import secrets
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aroman.authentication.phone import normalize_mobile
from aroman.authentication.sms import SMSProvider, get_sms_provider
from aroman.core.config import Settings, get_settings
from aroman.core.db import get_db, utcnow
from aroman.models import AuthChallenge, AuthSession, AuthVerifyAttempt, User

router = APIRouter(prefix="/auth", tags=["authentication"])
COOKIE_NAME = "aroman_session"


class MobileRequest(BaseModel):
    mobile: str = Field(min_length=10, max_length=32)


class VerifyRequest(MobileRequest):
    code: str = Field(pattern=r"^[0-9۰-۹٠-٩]{6}$")


def digest(value: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), value.encode(), hashlib.sha256).hexdigest()


def lock_rate_keys(db: Session, mobile_key: str, peer_key: str) -> None:
    """Serialize rate checks across workers on PostgreSQL before reading counters."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    keys = sorted(
        {
            int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)
            for value in ("mobile:" + mobile_key, "peer:" + peer_key)
        }
    )
    for key in keys:
        db.execute(select(func.pg_advisory_xact_lock(key)))


def client_digest(request: Request, settings: Settings) -> str:
    # Only a configured proxy can supply a forwarded client address.
    peer = request.client.host if request.client else "unknown"
    effective_peer = peer
    try:
        proxies = [
            ipaddress.ip_network(value.strip())
            for value in settings.trusted_proxy_cidrs.split(",")
            if value.strip()
        ]
        if proxies and any(ipaddress.ip_address(peer) in network for network in proxies):
            forwarded = request.headers.get("x-forwarded-for", "")
            hops = [ipaddress.ip_address(value.strip()) for value in forwarded.split(",")]
            effective_peer = str(hops[-1])
            for candidate in reversed(hops):
                if not any(candidate in network for network in proxies):
                    effective_peer = str(candidate)
                    break
    except ValueError:
        pass
    return digest(effective_peer, settings.otp_pepper)


def recent_count(db: Session, column, value: str, minutes: int) -> int:
    since = utcnow() - timedelta(minutes=minutes)
    return (
        db.scalar(
            select(func.count())
            .select_from(AuthChallenge)
            .where(column == value, AuthChallenge.created_at >= since)
        )
        or 0
    )


def check_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin and origin not in settings.origins:
        raise HTTPException(403, "Origin denied")


def aware(value):
    return value.replace(tzinfo=utcnow().tzinfo) if value.tzinfo is None else value


@router.post("/challenges", status_code=202)
def request_code(
    body: MobileRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    sms: SMSProvider = Depends(get_sms_provider),
):
    check_origin(request, settings)
    try:
        mobile = normalize_mobile(body.mobile)
    except ValueError:
        raise HTTPException(422, "Invalid mobile number") from None
    if settings.sms_provider == "unconfigured":
        raise HTTPException(503, "SMS delivery unavailable")
    mobile_key = digest(mobile, settings.otp_pepper)
    peer_key = client_digest(request, settings)
    lock_rate_keys(db, mobile_key, peer_key)
    # Per-mobile cooldown and rolling windows; per-peer limit curbs rotating numbers.
    latest = db.scalar(
        select(AuthChallenge)
        .where(AuthChallenge.mobile_digest == mobile_key)
        .order_by(AuthChallenge.created_at.desc(), AuthChallenge.id.desc())
    )
    if latest and (utcnow() - aware(latest.created_at)).total_seconds() < 60:
        raise HTTPException(429, "Try again later")
    if (
        recent_count(db, AuthChallenge.mobile_digest, mobile_key, 60) >= 5
        or recent_count(db, AuthChallenge.requester_digest, peer_key, 60) >= 20
    ):
        raise HTTPException(429, "Try again later")
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = AuthChallenge(
        mobile_digest=mobile_key,
        code_digest=digest(code, settings.otp_pepper),
        requester_digest=peer_key,
        expires_at=utcnow() + timedelta(minutes=settings.otp_minutes),
        attempts=0,
    )
    db.add(challenge)
    db.flush()
    try:
        sms.send_otp(mobile, code)
    except Exception:
        db.rollback()
        raise HTTPException(503, "SMS delivery unavailable") from None
    for old in db.scalars(
        select(AuthChallenge).where(
            AuthChallenge.mobile_digest == mobile_key,
            AuthChallenge.id != challenge.id,
            AuthChallenge.consumed_at.is_(None),
        )
    ):
        old.consumed_at = utcnow()
    db.commit()
    return {"message": "If delivery is available, a code has been sent"}


@router.post("/verify")
def verify_code(
    body: VerifyRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    check_origin(request, settings)
    try:
        mobile = normalize_mobile(body.mobile)
    except ValueError:
        raise HTTPException(422, "Invalid mobile number") from None
    mobile_key = digest(mobile, settings.otp_pepper)
    peer_key = client_digest(request, settings)
    lock_rate_keys(db, mobile_key, peer_key)
    since = utcnow() - timedelta(hours=1)
    peer_attempts = (
        db.scalar(
            select(func.count())
            .select_from(AuthVerifyAttempt)
            .where(
                AuthVerifyAttempt.requester_digest == peer_key,
                AuthVerifyAttempt.created_at >= since,
            )
        )
        or 0
    )
    mobile_attempts = (
        db.scalar(
            select(func.count())
            .select_from(AuthVerifyAttempt)
            .where(
                AuthVerifyAttempt.mobile_digest == mobile_key, AuthVerifyAttempt.created_at >= since
            )
        )
        or 0
    )
    if peer_attempts >= 30 or mobile_attempts >= 10:
        raise HTTPException(429, "Try again later")
    db.add(AuthVerifyAttempt(mobile_digest=mobile_key, requester_digest=peer_key))
    challenge = db.scalar(
        select(AuthChallenge)
        .where(AuthChallenge.mobile_digest == mobile_key)
        .order_by(AuthChallenge.created_at.desc(), AuthChallenge.id.desc())
        .with_for_update()
    )
    if (
        not challenge
        or challenge.consumed_at
        or aware(challenge.expires_at) <= utcnow()
        or challenge.attempts >= 5
    ):
        db.commit()
        raise HTTPException(400, "Invalid or expired code")
    challenge.attempts += 1
    normalized_code = "".join(str(int(char)) for char in body.code)
    if not hmac.compare_digest(challenge.code_digest, digest(normalized_code, settings.otp_pepper)):
        db.commit()
        raise HTTPException(429 if challenge.attempts >= 5 else 400, "Invalid or expired code")
    challenge.consumed_at = utcnow()
    # Older open challenges are invalidated after successful login.
    for old in db.scalars(
        select(AuthChallenge).where(
            AuthChallenge.mobile_digest == mobile_key,
            AuthChallenge.id != challenge.id,
            AuthChallenge.consumed_at.is_(None),
        )
    ):
        old.consumed_at = utcnow()
    user = db.scalar(select(User).where(User.mobile_e164 == mobile))
    if user is None:
        user = User(mobile_e164=mobile, role="customer")
        db.add(user)
        db.flush()
    if not user.is_active:
        db.commit()
        raise HTTPException(403, "Account unavailable")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session = AuthSession(
        user_id=user.id,
        token_digest=digest(token, settings.session_pepper),
        csrf_digest=digest(csrf, settings.session_pepper),
        expires_at=utcnow() + timedelta(hours=settings.session_hours),
    )
    db.add(session)
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.session_hours * 3600,
        path="/api/v1",
    )
    return {"user_id": user.id, "csrf_token": csrf}


def current_session(
    request: Request,
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthSession:
    if not token:
        raise HTTPException(401, "Authentication required")
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_digest == digest(token, settings.session_pepper)
        )
    )
    if (
        not session
        or session.revoked_at
        or aware(session.expires_at) <= utcnow()
        or not session.user.is_active
    ):
        raise HTTPException(401, "Authentication required")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request, settings)
        if not csrf or not hmac.compare_digest(
            session.csrf_digest, digest(csrf, settings.session_pepper)
        ):
            raise HTTPException(403, "CSRF token required")
    return session


@router.get("/session")
def read_session(session: AuthSession = Depends(current_session)):
    return {"user_id": session.user_id, "role": session.user.role}


@router.get("/csrf")
def rotate_csrf(
    request: Request,
    session: AuthSession = Depends(current_session),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    check_origin(request, settings)
    token = secrets.token_urlsafe(32)
    session.csrf_digest = digest(token, settings.session_pepper)
    db.commit()
    return {"csrf_token": token}


@router.delete("/session", status_code=204)
def logout(
    response: Response,
    session: AuthSession = Depends(current_session),
    db: Session = Depends(get_db),
):
    session.revoked_at = utcnow()
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/api/v1")
