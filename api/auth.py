"""Authentication primitives for the DOR API.

Authentication is separate from Phase 3 runtime authorization. A bootstrap user
may be configured through environment variables so the token endpoint is usable
without embedding credentials in source control.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

SECRET_KEY = os.getenv("DOR_JWT_SECRET_KEY")
ALGORITHM = os.getenv("DOR_JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("DOR_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

if not SECRET_KEY:
    raise RuntimeError("DOR_JWT_SECRET_KEY must be configured before starting the API")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
_users: dict[str, dict] = {}
fake_users_db = _users
_PBKDF2_ITERATIONS = 600_000


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class User(BaseModel):
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    disabled: bool = False


class UserInDB(User):
    hashed_password: str


def get_password_hash(password: str) -> str:
    """Hash a password with salted PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        scheme, iterations, salt_hex, digest_hex = hashed_password.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def bootstrap_configured_admin() -> None:
    """Create the explicitly configured bootstrap user, if credentials are supplied."""
    username = os.getenv("DOR_ADMIN_USERNAME", "admin").strip()
    password = os.getenv("DOR_ADMIN_PASSWORD")
    if not username or not password:
        return
    _users[username] = {
        "username": username,
        "email": os.getenv("DOR_ADMIN_EMAIL"),
        "full_name": os.getenv("DOR_ADMIN_FULL_NAME", username),
        "disabled": False,
        "hashed_password": get_password_hash(password),
    }


def get_user(db: dict, username: str) -> Optional[UserInDB]:
    user_dict = db.get(username)
    return UserInDB(**user_dict) if user_dict else None


def authenticate_user(db: dict, username: str, password: str) -> Optional[UserInDB]:
    user = get_user(db, username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    user = get_user(fake_users_db, username=username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_actor(current_user: User = Depends(get_current_active_user)):
    from domain.actor import Actor, ActorType
    return Actor(
        id=current_user.username,
        identity=current_user.full_name or current_user.username,
        type=ActorType.HUMAN,
    )


bootstrap_configured_admin()
