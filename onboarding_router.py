
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user, require_roles
from models import User, Role
from onboarding import Onboarding
from onboarding_schemas import (
    OnboardingCreate,
    OnboardingUpdate,
    OnboardingResponse
)

router = APIRouter(
    prefix="/onboarding",
    tags=["Employee Onboarding"]
)


# HR/Admin can assign onboarding tasks
@router.post("/", response_model=OnboardingResponse)
def create_onboarding(
    data: OnboardingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(Role.HR, Role.ADMIN)
    )
):
    task = Onboarding(**data.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# HR/Admin can view all onboarding tasks
@router.get("/", response_model=list[OnboardingResponse])
def get_onboarding(
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(Role.HR, Role.ADMIN)
    )
):
    return db.query(Onboarding).all()


# HR/Admin can update onboarding status
@router.put("/{task_id}", response_model=OnboardingResponse)
def update_onboarding(
    task_id: int,
    data: OnboardingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_roles(Role.HR, Role.ADMIN)
    )
):
    task = db.get(Onboarding, task_id)

    if not task:
        raise HTTPException(
            status_code=404,
            detail="Onboarding task not found"
        )

    task.status = data.status
    db.commit()
    db.refresh(task)

    return task
