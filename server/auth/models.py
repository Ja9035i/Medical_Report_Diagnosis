from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Role = Literal["patient", "doctor", "admin"]


class SignupRequest(BaseModel):
    """Public signup. Always creates a patient; any 'role' sent by the client is ignored."""
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=72)  # bcrypt only uses the first 72 bytes
    # Shown to doctors/admins only; stored with the account, never sent to the AI
    full_name: Optional[str] = Field(default=None, max_length=100)

    @field_validator("full_name")
    @classmethod
    def tidy_full_name(cls, value):
        value = " ".join((value or "").split())
        return value or None


class CreateUserRequest(SignupRequest):
    """Admin-only: create a user with an explicit role (e.g. a doctor)."""
    role: Role
