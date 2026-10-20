import os
import tempfile

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from alembic import command

temporary_database = tempfile.NamedTemporaryFile(prefix="aroman-test-", suffix=".db", delete=False)
path = temporary_database.name
temporary_database.close()
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{path}",
        "OTP_PEPPER": "test-otp-pepper-aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "SESSION_PEPPER": "test-session-pepper-bbbbbbbbbbbbbbbbbbbbbbbb",
        "ENVIRONMENT": "test",
        "SMS_PROVIDER": "fake",
        "FAKE_SMS_ENABLED": "true",
        "COOKIE_SECURE": "false",
    }
)

from aroman.authentication.sms import FakeSMS, get_sms_provider  # noqa: E402
from aroman.core.db import get_engine  # noqa: E402
from aroman.main import app  # noqa: E402
from aroman.seed import seed  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    with Session(get_engine()) as db:
        seed(db)
    yield
    command.downgrade(config, "base")
    os.unlink(path)


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture
def sms():
    provider = get_sms_provider()
    assert isinstance(provider, FakeSMS)
    provider.messages.clear()
    return provider


def login(client, sms, mobile="09121234567"):
    assert client.post("/api/v1/auth/challenges", json={"mobile": mobile}).status_code == 202
    code = sms.messages[-1][1]
    result = client.post("/api/v1/auth/verify", json={"mobile": mobile, "code": code})
    assert result.status_code == 200, result.text
    return result.json()["csrf_token"]
