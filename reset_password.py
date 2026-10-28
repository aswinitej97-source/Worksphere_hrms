
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import User, Role
from auth import hash_password, require_roles

router = APIRouter(
    prefix="/reset-password",
    tags=["Password Reset"]
)


class ResetPasswordRequest(BaseModel):
    user_id: int
    new_password: str = Field(min_length=8)


@router.post("/")
def reset_password(
    data: ResetPasswordRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles(Role.ADMIN)),
):
    user = db.get(User, data.user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    user.hashed_password = hash_password(
        data.new_password
    )

    db.commit()

    return {
        "message": "Password reset successfully"
    }
