"""Offline-only Kavenegar Lookup adapter. No network transport is supplied here."""

import re
from collections.abc import Mapping
from typing import Protocol

from aroman.authentication.sms import SMSDeliveryRejected


class LookupSimulation(Protocol):
    """Explicitly injected simulator for a Lookup response; never a live client."""

    def lookup(self, parameters: Mapping[str, str]) -> object: ...


class SMSDeliveryUncertain(Exception):
    """Submission may have happened; do not retry automatically."""


# Documented Lookup errors that prove this particular submission was refused.
# 402 is generic failure and 409 is server unavailability, so neither is conclusive.
_REJECTION_STATUSES = frozenset({400, 401, 403, 404, 405, 406, 407, 411, 418, 422,
                                 424, 426, 431, 432, 501})
_ACCEPTED_MESSAGE_STATUSES = frozenset({1, 2, 4, 5, 10})


class KavenegarSMS:
    """Prepare Lookup parameters and interpret one simulated provider response."""

    def __init__(self, *, template: str, transport: LookupSimulation) -> None:
        if not isinstance(template, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", template):
            raise ValueError("Invalid verification template")
        self._template = template
        self._transport = transport

    def send_otp(self, mobile: str, code: str) -> None:
        if not isinstance(mobile, str) or not re.fullmatch(r"\+989[0-9]{9}", mobile):
            raise ValueError("Invalid normalized mobile")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
            raise ValueError("Invalid OTP")

        # Lookup's documented domestic example uses 09..., while AROMAN retains +989...
        parameters = {"receptor": "0" + mobile[3:], "token": code, "template": self._template}
        try:
            response = self._transport.lookup(parameters)
        except Exception:
            # An exception may include secrets in its text. Suppress its context.
            raise SMSDeliveryUncertain("SMS submission uncertain") from None

        if not isinstance(response, dict):
            raise SMSDeliveryUncertain("SMS submission uncertain")
        returned = response.get("return")
        if not isinstance(returned, dict):
            raise SMSDeliveryUncertain("SMS submission uncertain")
        status = returned.get("status")
        if type(status) is not int:
            raise SMSDeliveryUncertain("SMS submission uncertain")
        entries = response.get("entries")

        if status == 200:
            if (
                isinstance(entries, list)
                and len(entries) == 1
                and isinstance(entries[0], dict)
                and type(entries[0].get("messageid")) is int
                and entries[0]["messageid"] > 0
                and type(entries[0].get("status")) is int
                and entries[0]["status"] in _ACCEPTED_MESSAGE_STATUSES
            ):
                return
        elif status in _REJECTION_STATUSES and entries in (None, []):
            raise SMSDeliveryRejected("SMS submission rejected")
        raise SMSDeliveryUncertain("SMS submission uncertain")
