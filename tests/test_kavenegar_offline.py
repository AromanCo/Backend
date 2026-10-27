import logging
import socket

import pytest

from aroman.authentication.kavenegar import KavenegarSMS, SMSDeliveryUncertain
from aroman.authentication.sms import (
    FakeSMS,
    SMSDeliveryRejected,
    UnconfiguredSMS,
    get_sms_provider,
)
from aroman.core.config import Settings

MOBILE = "+989121234567"  # Synthetic documentation number; never dispatched.
CODE = "012345"
TEMPLATE = "SyntheticTestTemplate"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Kavenegar adapter test attempted a real network connection")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket.socket, "connect_ex", fail)
    monkeypatch.setattr(socket, "create_connection", fail)


class Simulation:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def lookup(self, parameters):
        self.calls.append(dict(parameters))
        if self.error:
            raise self.error
        return self.result


def accepted(status=1):
    return {"return": {"status": 200}, "entries": [{"messageid": 123, "status": status}]}


def test_lookup_mapping_and_accepted_submission():
    simulation = Simulation(accepted())
    KavenegarSMS(template=TEMPLATE, transport=simulation).send_otp(MOBILE, CODE)
    assert simulation.calls == [
        {"receptor": "09121234567", "token": CODE, "template": TEMPLATE}
    ]
    assert MOBILE == "+989121234567"


@pytest.mark.parametrize("status", [400, 418, 424, 426, 431, 432])
def test_documented_definite_refusal(status):
    simulation = Simulation({"return": {"status": status}, "entries": None})
    with pytest.raises(SMSDeliveryRejected, match="^SMS submission rejected$"):
        KavenegarSMS(template=TEMPLATE, transport=simulation).send_otp(MOBILE, CODE)
    assert len(simulation.calls) == 1


@pytest.mark.parametrize(
    "result",
    [
        None,
        {"return": {"status": 200}},
        {"return": {"status": 200}, "entries": []},
        {"return": {"status": 200}, "entries": [{"messageid": 1, "status": 6}]},
        {"return": {"status": 200}, "entries": [{"messageid": True, "status": 1}]},
        {"return": {"status": "424"}, "entries": None},
        {"return": {"status": 424}, "entries": [{"messageid": 1, "status": 1}]},
        {"return": {"status": 402}, "entries": None},
        {"return": {"status": 409}, "entries": None},
        {"return": {"status": 999}, "entries": None},
    ],
)
def test_ambiguous_or_malformed_response_is_uncertain(result):
    simulation = Simulation(result)
    with pytest.raises(SMSDeliveryUncertain, match="^SMS submission uncertain$"):
        KavenegarSMS(template=TEMPLATE, transport=simulation).send_otp(MOBILE, CODE)
    assert len(simulation.calls) == 1


@pytest.mark.parametrize("error", [TimeoutError("secret"), ConnectionError("secret")])
def test_transport_failure_is_uncertain_and_never_retried_or_logged(error, caplog):
    caplog.set_level(logging.DEBUG)
    simulation = Simulation(error=error)
    with pytest.raises(SMSDeliveryUncertain) as raised:
        KavenegarSMS(template=TEMPLATE, transport=simulation).send_otp(MOBILE, CODE)
    assert len(simulation.calls) == 1
    visible = str(raised.value) + caplog.text
    for secret in (MOBILE, "09121234567", CODE, TEMPLATE, "secret", "api-key", "https://"):
        assert secret not in visible


@pytest.mark.parametrize(
    ("result", "exception_type"),
    [
        (
            {"return": {"status": 424, "message": "secret-provider-text"}, "entries": None},
            SMSDeliveryRejected,
        ),
        (
            {"return": {"status": 200, "message": "secret-provider-text"},
             "entries": [{"message": CODE, "receptor": MOBILE}]},
            SMSDeliveryUncertain,
        ),
    ],
)
def test_provider_payload_is_never_exposed(result, exception_type, caplog):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(exception_type) as raised:
        KavenegarSMS(template=TEMPLATE, transport=Simulation(result)).send_otp(MOBILE, CODE)
    visible = str(raised.value) + caplog.text
    for secret in (MOBILE, CODE, "secret-provider-text"):
        assert secret not in visible


@pytest.mark.parametrize("mobile", ["09121234567", "+98912", "+98912abcdef", None])
@pytest.mark.parametrize("code", [CODE, "12345", "1234567", "12345x", None])
def test_invalid_inputs_never_reach_transport(mobile, code):
    simulation = Simulation(accepted())
    if mobile == MOBILE and code == CODE:
        pytest.fail("Invalid-input matrix contains a valid pair")
    with pytest.raises(ValueError):
        KavenegarSMS(template=TEMPLATE, transport=simulation).send_otp(mobile, code)
    assert simulation.calls == []


@pytest.mark.parametrize("template", ["", " ", "bad_name", "bad name", None])
def test_missing_or_invalid_template_fails_before_dispatch(template):
    simulation = Simulation(accepted())
    with pytest.raises(ValueError, match="^Invalid verification template$"):
        KavenegarSMS(template=template, transport=simulation)
    assert simulation.calls == []


def test_runtime_provider_selection_stays_safe():
    assert isinstance(get_sms_provider(), FakeSMS)
    assert Settings(sms_provider="unconfigured").sms_provider == "unconfigured"
    with pytest.raises(ValueError):
        Settings(sms_provider="kavenegar")
    fake = FakeSMS()
    fake.send_otp(MOBILE, CODE)
    assert fake.messages == [(MOBILE, CODE)]
    with pytest.raises(RuntimeError, match="SMS delivery is not configured"):
        UnconfiguredSMS().send_otp(MOBILE, CODE)


def test_network_guard_catches_a_transport_that_attempts_connect():
    class BadSimulation:
        def lookup(self, parameters):
            socket.create_connection(("127.0.0.1", 1))

    with pytest.raises(BaseException, match="real network connection"):
        KavenegarSMS(template=TEMPLATE, transport=BadSimulation()).send_otp(MOBILE, CODE)
