
from sqlalchemy import Column, Integer, String, Text, Date, ForeignKey
from database import Base


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    assigned_to = Column(
        Integer,
        ForeignKey("employees.id"),
        nullable=False
    )
    title = Column(String(255), nullable=False)
    description = Column(Text)
    due_date = Column(Date)
    status = Column(
        String(20),
        default="PENDING",
        nullable=False
    )
