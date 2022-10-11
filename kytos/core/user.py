"""User authentification """
import hashlib

from datetime import datetime
from typing import Literal, Optional

# pylint: disable=no-name-in-module
from pydantic import BaseModel, EmailStr, Field, constr, validator


class DocumentBaseModel(BaseModel):
    """DocumentBaseModel"""

    id: str = Field(None, alias="_id")
    inserted_at: Optional[datetime]
    updated_at: Optional[datetime]
    deleted_at: Optional[datetime]

    def dict(self, **kwargs) -> dict:
        """Model to dict."""
        values = super().dict(**kwargs)
        if "id" in values and values["id"]:
            values["_id"] = values["id"]
        if "exclude" in kwargs and "_id" in kwargs["exclude"]:
            values.pop("_id")
        return values


class UserDoc(DocumentBaseModel):
    """UserDocumentModel."""

    username: str
    state: Literal['active', 'inactive'] = 'active'
    password: constr(min_length=8)
    email: EmailStr

    @validator('password')
    # pylint: disable=no-self-argument
    def have_digit_letter(cls, password):
        """Check if password has at least a letter and a number"""
        upper = False
        lower = False
        number = False
        for char in password:
            if char.isupper():
                upper = True
            if char.isnumeric():
                number = True
            if char.islower():
                lower = True
            if number and upper and lower:
                return hashlib.sha512(password.encode()).hexdigest()
        raise ValueError('Password should contain:\n',
                         '1. Minimun 8 characters.\n',
                         '2. At least one upper case character.\n',
                         '3. At least 1 numeric character [0-9].')
