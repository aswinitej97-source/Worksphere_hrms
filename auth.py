import os
from datetime import datetime, timedelta, timezone

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from database import get_db
from models import Role, User

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError(
        "Set SECRET_KEY in your .env file "
        "with at least 32 characters"
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

password_hash = PasswordHash.recommended()

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="auth/login"
)


# Password helpers

def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(
    password: str,
    hashed_password: str,
) -> bool:
    return password_hash.verify(
        password,
        hashed_password,
    )


# JWT creation

def create_access_token(
    user_id: int,
    role: Role,
) -> str:
    now = datetime.now(timezone.utc)
    current_role = Role(role)

    payload = {
        "sub": str(user_id),
        "role": current_role.value,
        "iat": now,
        "exp": now + timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        ),
    }

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


# Authentication and account validation

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={
                "require": [
                    "sub",
                    "role",
                    "iat",
                    "exp",
                ]
            },
        )

        subject = payload["sub"]

        if not isinstance(subject, str):
            raise ValueError("Invalid token subject")

        user_id = int(subject)

        if user_id <= 0:
            raise ValueError("Invalid user ID")

        token_role = Role(payload["role"])

    except (
        jwt.InvalidTokenError,
        ValueError,
        TypeError,
        KeyError,
    ):
        raise credentials_error from None

    user = db.get(User, user_id)

    if user is None:
        raise credentials_error

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Your account is deactivated. "
                "Contact your admin."
            ),
        )

    try:
        database_role = Role(user.role)
    except (ValueError, TypeError):
        raise credentials_error from None

    if database_role != token_role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your role has changed. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# Role-based authorization
# Include Role.ADMIN explicitly on routes that admins can access.

def require_roles(*allowed_roles: Role):
    permitted_roles = {
        Role(role)
        for role in allowed_roles
    }

    def check_role(
        user: User = Depends(get_current_user),
    ) -> User:
        if Role(user.role) not in permitted_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission",
            )

        return user

    return check_role