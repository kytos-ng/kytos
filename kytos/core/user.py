"""User authentification """
# pylint: disable=no-name-in-module, no-self-argument
import hashlib
import os
from datetime import datetime
from typing import Literal, Optional

from pydantic import (BaseModel, EmailStr, Field, ValidationInfo,
                      field_validator)
from typing_extensions import Annotated


class DocumentBaseModel(BaseModel):
    """DocumentBaseModel"""

    id: str = Field(None, alias="_id")
    inserted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    def dict(self, **kwargs) -> dict:
        """Model to dict."""
        values = super().dict(**kwargs)
        if "id" in values and values["id"]:
            values["_id"] = values["id"]
        if "exclude" in kwargs and "_id" in kwargs["exclude"]:
            values.pop("_id")
        return values


def hashing(password: bytes, values: dict) -> str:
    """Hash password and return it as string"""
    return hashlib.scrypt(password=password, salt=values['salt'],
                          n=values['n'], r=values['r'],
                          p=values['p']).hex()


def validate_password(password: str, values: ValidationInfo):
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
            return hashing(password.encode(), values.data['hash'].dict())
    raise ValueError('value should contain ' +
                     'minimun 8 characters, ' +
                     'at least one upper case character, ' +
                     'at least 1 numeric character [0-9]')


class HashSubDoc(BaseModel):
    """HashSubDoc. Parameters for hash.scrypt function"""
    salt: bytes = Field(default=None, validate_default=True)
    n: int = 8192
    r: int = 8
    p: int = 1

    @field_validator('salt', mode='before')
    @classmethod
    def create_salt(cls, salt):
        """Create random salt value"""
        return salt or os.urandom(16)


class UserDoc(DocumentBaseModel):
    """UserDocumentModel."""

    username: str = Field(
        min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$'
    )
    hash: HashSubDoc
    state: Literal['active', 'inactive'] = 'active'
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)

    _validate_password = field_validator('password')(validate_password)

    @staticmethod
    def projection() -> dict:
        """Base model for projection."""
        return {
            "_id": 0,
            "username": 1,
            "email": 1,
            'password': 1,
            'hash': 1,
            'state': 1,
            'inserted_at': 1,
            'updated_at': 1,
            'deleted_at': 1
        }

    @staticmethod
    def projection_nopw() -> dict:
        """Model for projection without password"""
        return {
            "_id": 0,
            "username": 1,
            "email": 1,
            'state': 1,
            'inserted_at': 1,
            'updated_at': 1,
            'deleted_at': 1
        }


class UserDocUpdate(DocumentBaseModel):
    "UserDocUpdate use to validate data before updating"

    username: Optional[Annotated[str,
                                 Field(min_length=1, max_length=64,
                                       pattern=r'^[a-zA-Z0-9_-]+$')]] = None
    email: Optional[EmailStr] = None
    hash: Optional[HashSubDoc] = None
    password: Optional[Annotated[str,
                                 Field(min_length=8, max_length=64)]] = None

    _validate_password = field_validator('password')(validate_password)
