from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["patient", "doctor", "admin"]


class SignupRequest(BaseModel):
    """Public signup. Always creates a patient; any 'role' sent by the client is ignored."""
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=72)  # bcrypt only uses the first 72 bytes


class CreateUserRequest(SignupRequest):
    """Admin-only: create a user with an explicit role (e.g. a doctor)."""
    role: Role
