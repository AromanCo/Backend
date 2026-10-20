from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = ""
    otp_pepper: str = ""
    session_pepper: str = ""
    sms_provider: Literal["unconfigured", "fake"] = "unconfigured"
    fake_sms_enabled: bool = False
    cors_origins: str = "http://localhost:3000"
    trusted_proxy_cidrs: str = ""
    cookie_secure: bool = True
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    session_hours: int = 24 * 7
    otp_minutes: int = 5
    max_concept_notes: int = 6

    @field_validator("environment")
    @classmethod
    def check_environment(cls, value: str) -> str:
        if value not in {"development", "test", "production", "staging"}:
            raise ValueError("Invalid environment")
        return value

    @model_validator(mode="after")
    def secure_configuration(self) -> "Settings":
        if not self.database_url:
            raise ValueError("DATABASE_URL is required")
        if len(self.otp_pepper) < 32 or len(self.session_pepper) < 32:
            raise ValueError("OTP_PEPPER and SESSION_PEPPER must have at least 32 characters")
        if self.otp_pepper == self.session_pepper:
            raise ValueError("OTP and session peppers must differ")
        if self.sms_provider == "fake" and (
            self.environment not in {"development", "test"} or not self.fake_sms_enabled
        ):
            raise ValueError("Fake SMS requires explicit opt-in in development or test")
        if self.environment in {"production", "staging"}:
            if not self.cookie_secure or self.sms_provider == "fake":
                raise ValueError("Secure cookies and a real SMS provider are required")
            if self.database_url.startswith("sqlite"):
                raise ValueError("PostgreSQL is required in real environments")
            if not self.origins or any(
                not origin.startswith("https://") for origin in self.origins
            ):
                raise ValueError("Real environments require explicit HTTPS CORS origins")
        if "*" in self.origins or any(origin.endswith("/") for origin in self.origins):
            raise ValueError("CORS origins must be explicit origins without trailing slashes")
        if self.cookie_samesite not in {"lax", "strict", "none"}:
            raise ValueError("Invalid SameSite policy")
        if self.cookie_samesite == "none" and not self.cookie_secure:
            raise ValueError("SameSite=None requires secure cookies")
        if self.max_concept_notes < 1 or self.session_hours < 1 or self.otp_minutes < 1:
            raise ValueError("Durations and MAX_CONCEPT_NOTES must be positive")
        return self

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
