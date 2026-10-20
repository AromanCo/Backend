from typing import Protocol

from aroman.core.config import get_settings


class SMSProvider(Protocol):
    def send_otp(self, mobile: str, code: str) -> None: ...


class UnconfiguredSMS:
    def send_otp(self, mobile: str, code: str) -> None:
        raise RuntimeError("SMS delivery is not configured")


class FakeSMS:
    """Local only; messages stay in memory and are never returned by the API."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def send_otp(self, mobile: str, code: str) -> None:
        self.messages.append((mobile, code))


_provider: SMSProvider | None = None


def get_sms_provider() -> SMSProvider:
    global _provider
    if _provider is None:
        _provider = FakeSMS() if get_settings().sms_provider == "fake" else UnconfiguredSMS()
    return _provider
