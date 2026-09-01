"""Authentication token endpoint."""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from api.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    authenticate_configured_user,
    bootstrap_configured_admin,
    create_access_token,
)
from api.models import Token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Token:
    """Authenticate a configured admin and issue a JWT access token."""
    bootstrap_configured_admin()
    user = authenticate_configured_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={
            "sub": user.username,
            "cv": user.credential_version,
            "org": user.organization_id,
        },
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return Token(access_token=access_token, token_type="bearer")
