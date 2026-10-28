
from sqlalchemy import Column, Integer, String, Date, ForeignKey
from database import Base

class Onboarding(Base):
    __tablename__ = "onboarding"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    task_name = Column(String(255), nullable=False)
    status = Column(String(20), default="PENDING")
    due_date = Column(Date)
