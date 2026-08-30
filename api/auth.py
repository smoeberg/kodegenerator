"""Authentication primitives for the DOR API.

Authentication is separate from Phase 3 runtime authorization. The HTTP user
store is **process-local** (in-memory): it is intentionally limited to a
bootstrap admin configured via environment variables so the token endpoint is
usable without embedding credentials in source control.

Production must set ``DOR_JWT_SECRET_KEY`` and ``DOR_ADMIN_PASSWORD`` (enforced
at import of ``api.main``). Multi-instance or durable identity requires an
external IdP or a future persistent principal store — do not treat this module
as a multi-tenant user directory.
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

from infrastructure.runtime.db import build_session_factory
from services.identity_store import IdentityStore

IS_PRODUCTION = os.getenv("DOR_ENV", "development").lower() == "production"
SECRET_KEY = os.getenv("DOR_JWT_SECRET_KEY") or ("" if IS_PRODUCTION else "dev-insecure-secret-key-32-chars-long-xxx")
ALGORITHM = os.getenv("DOR_JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("DOR_ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

if IS_PRODUCTION and not SECRET_KEY:
    raise RuntimeError("DOR_JWT_SECRET_KEY must be configured in production before starting the API")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
# Process-local bootstrap store. Not durable across restarts or instances.
_users: dict[str, dict] = {}
# Public alias kept for tests and the token endpoint; prefer treating this as
# an ephemeral bootstrap map, not a general user directory.
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
    credential_version: int = 1


_identity_store: IdentityStore | None = None
_identity_store_url: str | None = None


def get_identity_store() -> IdentityStore | None:
    """Return the configured durable store, or the development test fallback."""
    global _identity_store, _identity_store_url
    database_url = os.getenv("DOR_IDENTITY_DATABASE_URL")
    if IS_PRODUCTION and not database_url:
        database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return None
    if _identity_store is None or _identity_store_url != database_url:
        _identity_store = IdentityStore(build_session_factory(database_url))
        _identity_store_url = database_url
    return _identity_store


def get_password_hash(password: str) -> str:
    """Hash a password with salted PBKDF2-HMAC-SHA256."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a PBKDF2 hash."""
    try:
        scheme, iterations, salt_hex, digest_hex = hashed_password.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def bootstrap_configured_admin() -> None:
    """Synchronize the explicitly configured bootstrap user from environment settings.

    In production, a missing password is already rejected by
    ``api.main.validate_production_security_configuration``. This helper still
    no-ops without credentials in development so unit tests can inject users
    directly into the process-local store.
    """
    username = os.getenv("DOR_ADMIN_USERNAME", "admin").strip()
    password = os.getenv("DOR_ADMIN_PASSWORD")
    if not username or not password:
        if IS_PRODUCTION:
            raise RuntimeError(
                "DOR_ADMIN_USERNAME and DOR_ADMIN_PASSWORD must both be set "
                "in production before bootstrapping the API user store"
            )
        return
    store = get_identity_store()
    if store is not None and store.get(username) is not None:
        return
    identity = {
        "username": username,
        "email": os.getenv("DOR_ADMIN_EMAIL"),
        "full_name": os.getenv("DOR_ADMIN_FULL_NAME", username),
        "disabled": False,
        "hashed_password": get_password_hash(password),
        "credential_version": 1,
    }
    if store is not None:
        store.create_if_absent(
            username=username,
            hashed_password=identity["hashed_password"],
            email=identity["email"],
            full_name=identity["full_name"],
        )
        return
    _users[username] = identity


def get_user(db: dict, username: str) -> Optional[UserInDB]:
    """Look up a user by username."""
    user_dict = db.get(username)
    return UserInDB(**user_dict) if user_dict else None


def authenticate_user(db: dict, username: str, password: str) -> Optional[UserInDB]:
    """Authenticate a user against the supplied database."""
    user = get_user(db, username)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def get_configured_user(username: str) -> Optional[UserInDB]:
    """Resolve a principal from durable production storage or the test map."""
    store = get_identity_store()
    if store is not None:
        value = store.get(username)
        return UserInDB(**value) if value else None
    return get_user(fake_users_db, username)


def authenticate_configured_user(
    username: str, password: str
) -> Optional[UserInDB]:
    user = get_configured_user(username)
    if not user or user.disabled or not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def authenticate_access_token(token: str) -> User:
    """Validate a JWT and resolve its subject to a configured user.

    This synchronous primitive is shared by HTTP, SSE, and WebSocket
    authentication so every transport enforces the same signature, expiry,
    subject, user-existence, and disabled-user checks.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not isinstance(username, str) or not username.strip():
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc
    user = get_configured_user(username=username)
    if user is None or user.disabled:
        raise credentials_exception
    store = get_identity_store()
    if store is not None:
        token_version = payload.get("cv")
        if type(token_version) is not int or token_version != user.credential_version:
            raise credentials_exception
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Decode a bearer token and return its active user."""
    return authenticate_access_token(token)


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Reject disabled users."""
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_actor(current_user: User = Depends(get_current_active_user)):
    """Map the authenticated user to the domain actor model."""
    from domain.actor import Actor, ActorType
    return Actor(id=current_user.username, identity=current_user.full_name or current_user.username, type=ActorType.HUMAN)


bootstrap_configured_admin()
