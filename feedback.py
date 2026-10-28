
from sqlalchemy import Column, Integer, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from database import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(
        Integer,
        ForeignKey("employees.id"),
        nullable=False
    )
    message = Column(Text, nullable=False)
    rating = Column(Integer, nullable=False)
    created_at = Column(
        DateTime,
        server_default=func.now()
    )
