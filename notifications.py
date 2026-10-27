from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from auth import get_current_user, require_roles
from database import get_db
from models import Notification, Role, User
from schemas import NotificationResponse


router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"],
)


def create_notification(
    db: Session,
    user_id: int,
    title: str,
    message: str,
):
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        is_read=False,
    )

    db.add(notification)
    return notification


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    count = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
    )

    return {
        "unread_count": count or 0
    }


@router.patch("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
        )
        .values(is_read=True)
    )

    db.commit()

    return {
        "updated_count": result.rowcount
    }


@router.get(
    "",
    response_model=list[NotificationResponse],
)
def list_notifications(
    unread_only: bool = False,
    offset: int = Query(
        default=0,
        ge=0,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(Notification).where(
        Notification.user_id == user.id
    )

    if unread_only:
        query = query.where(
            Notification.is_read.is_(False)
        )

    return db.scalars(
        query
        .order_by(Notification.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()


@router.patch(
    "/{notification_id}/read",
    response_model=NotificationResponse,
)
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )

    if notification is None:
        raise HTTPException(
            status_code=404,
            detail="Notification not found",
        )

    notification.is_read = True

    db.commit()
    db.refresh(notification)

    return notification


@router.post(
    "/alert/{user_id}",
    response_model=NotificationResponse,
)
def create_smart_alert(
    user_id: int,
    title: str,
    message: str,
    db: Session = Depends(get_db),
    manager: User = Depends(
        require_roles(Role.HR, Role.ADMIN)
    ),
):
    target_user = db.scalar(
        select(User).where(
            User.id == user_id
        )
    )

    if target_user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    notification = create_notification(
        db=db,
        user_id=user_id,
        title=title,
        message=message,
    )

    db.commit()
    db.refresh(notification)

    return notification