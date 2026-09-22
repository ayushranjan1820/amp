from pydantic import BaseModel, field_validator, model_validator, Field
from typing import Self
import re
from datetime import datetime
from agents.agent_config import ToolConfig, ModelConfig, Visibility, Status


def _validate_email_format(val: str):
    """
    Checks if a given email matches the following conditions to be valid
    1. Should contain @ symbol
    2. Should contain . symbol
    3. Should contain at least one character before @
    4. Should contain at least one character after .
    5. Should not contain any whitespace characters

    args:
        val: str (The email string given by user)
    returns:
        bool: True for valid email otherwise False or raises Exception
    """
    if re.search(r"@", val) == None:
        raise ValueError("Email must contain @ symbol.")

    if re.search(r"\.", val) == None:
        raise ValueError("Email must contain . symbol.")

    if re.search(r"^[^@]+@.*", val) == None:
        raise ValueError("Email must contain at least one character before @")

    if re.search(r".*\..*", val) == None:
        raise ValueError("Email must contain at least one character after .")

    if re.search(r"\s", val) != None:
        raise ValueError("Email must not contain any whitespace characters.")

    return val


class RegisterUserReq(BaseModel):
    name: str
    email: str
    password: str
    confirm_password: str

    @field_validator("email")
    @classmethod
    def check_email_format(cls, val: str):
        return _validate_email_format(val)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, val: str):
        """
        Checks if a given password matches following conditions to be valid
        1. Should contain 1 uppercase alphabet
        2. Should contain 1 lowercase alphabet
        3. Should contain 1 digit
        4. Should contain 1 special character
        5. Should be minimum 8 characters long
        6. Should not contain any whitespace characters

        args:
            val: str (The password string given by user)
        returns:
            bool: True for valid password otherwise False or raises Exception
        """
        if len(val) < 8:
            raise ValueError("Password must be at least 8 characters long.")

        # check for digit
        if re.search(r"\d", val) == None:
            raise ValueError("Password must contain at least one digit.")

        # check for uppercase alphabet
        if re.search(r"[A-Z]", val) == None:
            raise ValueError("Password must contain at least one uppercase alphabet.")

        # check for lowercase alphabet
        if re.search(r"[a-z]", val) == None:
            raise ValueError("Password must contain at least one lowercase alphabet.")

        # check for special character('@,#,$,%,&,!')
        if re.search(r"[@#$%&!]", val) == None:
            raise ValueError(
                "Password must contain at least one special character from (@,#,$,%,&,!)"
            )

        # check for whitespace
        if re.search(r"\s", val) != None:
            raise ValueError("Password must not contain any whitespace characters.")

        return val

    @model_validator(mode="after")
    def check_confirm_password(self) -> Self:
        """
        Checks if password and confirm_password match.
        """
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class LoginUserReq(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def check_email_format(cls, val: str):
        return _validate_email_format(val)


class NewAgentReq(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[ToolConfig] = []
    model: ModelConfig
    capabilities: list[str] = []
    enabled: bool = True
    version: str
    visibility: Visibility = Field(default_factory=lambda: Visibility.PRIVATE)
    status: Status = Field(default_factory=lambda: Status.DRAFT)


class ChatReq(BaseModel):
    message: str