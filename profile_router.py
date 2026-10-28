
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from database import get_db
from models import User
from auth import (
    get_current_user,
    hash_password,
    verify_password
)

router = APIRouter(
    prefix="/profile",
    tags=["Profile & Settings"]
)


class ProfileUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=50)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


@router.get("/me")
def get_profile(
    current_user: User = Depends(get_current_user)
):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role
    }


@router.put("/me")
def update_profile(
    data: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    current_user.username = data.username

    try:
        db.commit()
        db.refresh(current_user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Username already exists"
        )

    return {
        "message": "Profile updated successfully"
    }


@router.put("/change-password")
def change_password(
    data: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not verify_password(
        data.old_password,
        current_user.hashed_password
    ):
        raise HTTPException(
            status_code=400,
            detail="Old password is incorrect"
        )

    if data.old_password == data.new_password:
        raise HTTPException(
            status_code=400,
            detail="New password must be different"
        )

    current_user.hashed_password = hash_password(
        data.new_password
    )

    db.commit()

    return {
        "message": "Password changed successfully"
    }
