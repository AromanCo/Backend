import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from aroman.authentication.api import current_session
from aroman.models import AuthSession

router = APIRouter(prefix="/users", tags=["users"])


class UserOut(BaseModel):
    id: uuid.UUID
    mobile_e164: str
    role: str


@router.get("/me", response_model=UserOut)
def me(session: AuthSession = Depends(current_session)):
    return UserOut(id=session.user.id, mobile_e164=session.user.mobile_e164, role=session.user.role)
