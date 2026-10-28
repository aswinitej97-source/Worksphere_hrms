
from sqlalchemy import (
    Column,
    Integer,
    Boolean,
    ForeignKey
)
from database import Base


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        unique=True,
        nullable=False
    )

    email_notifications = Column(
        Boolean,
        default=True,
        nullable=False
    )

    task_notifications = Column(
        Boolean,
        default=True,
        nullable=False
    )

    announcement_notifications = Column(
        Boolean,
        default=True,
        nullable=False
    )
