"""Authentication token endpoint."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from api.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    authenticate_configured_user,
    create_access_token,
    ensure_bootstrap_runtime_context,
)
from api.models import Token
from services.login_rate_limiter import LoginRateLimiter

router = APIRouter(prefix="/auth", tags=["auth"])
_login_rate_limiter = LoginRateLimiter.from_environment()


def _peer_ip(request: Request) -> str:
    """Use the direct peer address; do not trust forwarded headers implicitly."""
    return request.client.host if request.client is not None else "unknown"


def _rate_limited(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Too many login attempts",
        headers={"Retry-After": str(max(1, retry_after))},
    )


@router.post("/token", response_model=Token)
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Token:
    """Authenticate a configured admin and issue a JWT access token."""
    peer_ip = _peer_ip(request)
    retry_after = _login_rate_limiter.retry_after(peer_ip, form_data.username)
    if retry_after:
        raise _rate_limited(retry_after)

    user = authenticate_configured_user(form_data.username, form_data.password)
    if not user:
        retry_after = _login_rate_limiter.record_failure(peer_ip, form_data.username)
        if retry_after:
            raise _rate_limited(retry_after)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    _login_rate_limiter.record_success(peer_ip, form_data.username)
    # Seed runtime membership only after credentials have been verified. Failed
    # login attempts therefore cannot trigger bootstrap database/runtime work.
    ensure_bootstrap_runtime_context()
    access_token = create_access_token(
        data={
            "sub": user.username,
            "cv": user.credential_version,
            "org": user.organization_id,
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")
