from fastapi import FastAPI

import analytics
import attendance
import documents
import employees
import leaves
import notifications
import payroll
import performance
import shifts

from database import Base, engine


# Create database tables
Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="WorkSphere HRMS",
    description="Smart HR Management System",
    version="3.0.0",
)


# Employees
app.include_router(employees.router)

# Attendance
app.include_router(attendance.router)

# Leaves
app.include_router(leaves.router)

# Payroll
app.include_router(payroll.router)

# Notifications
app.include_router(notifications.router)

# Analytics
app.include_router(analytics.router)

# Phase 3 - Shifts
app.include_router(shifts.router)

# Phase 3 - Documents
app.include_router(documents.router)

# Phase 3 - Performance
app.include_router(performance.router)


@app.get("/")
def root():
    return {
        "message": "WorkSphere HRMS API is running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }