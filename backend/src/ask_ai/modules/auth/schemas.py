from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: SecretStr
    display_name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name cannot be empty")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < 12:
            raise ValueError("Password must contain at least 12 characters")
        if len(raw) > 128 or len(raw.encode("utf-8")) > 1024:
            raise ValueError("Password must not exceed 128 characters or 1024 UTF-8 bytes")
        if "\x00" in raw:
            raise ValueError("Password must not contain a null character")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr

    @field_validator("password")
    @classmethod
    def validate_password_size(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw or len(raw) > 128 or len(raw.encode("utf-8")) > 1024 or "\x00" in raw:
            raise ValueError("Invalid password")
        return value


class OAuthExchangeRequest(BaseModel):
    code: str = Field(min_length=32, max_length=256)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    display_name: str | None
    email_verified: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    csrf_token: str
    user: UserResponse


class AuthProvidersResponse(BaseModel):
    providers: list[str]


class CsrfTokenResponse(BaseModel):
    csrf_token: str
