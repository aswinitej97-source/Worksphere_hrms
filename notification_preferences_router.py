
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from models import User
from notification_preferences import NotificationPreference


router = APIRouter(
    prefix="/notification-preferences",
    tags=["Notification Preferences"]
)


class PreferenceUpdate(BaseModel):
    email_notifications: bool = True
    task_notifications: bool = True
    announcement_notifications: bool = True


class PreferenceResponse(PreferenceUpdate):
    model_config = ConfigDict(from_attributes=True)


@router.get("/me", response_model=PreferenceResponse)
def get_preferences(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    preference = db.query(NotificationPreference).filter(
        NotificationPreference.user_id == current_user.id
    ).first()

    if not preference:
        return PreferenceResponse()

    return preference


@router.put("/me", response_model=PreferenceResponse)
def update_preferences(
    data: PreferenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    preference = db.query(NotificationPreference).filter(
        NotificationPreference.user_id == current_user.id
    ).first()

    if not preference:
        preference = NotificationPreference(
            user_id=current_user.id
        )
        db.add(preference)

    preference.email_notifications = data.email_notifications
    preference.task_notifications = data.task_notifications
    preference.announcement_notifications = (
        data.announcement_notifications
    )

    db.commit()
    db.refresh(preference)

    return preference
