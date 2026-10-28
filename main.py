
from fastapi import FastAPI

from database import Base, engine



# Existing Modules
import analytics
import attendance
import documents
import employees
import leaves
import notifications
import payroll
import performance
import shifts
import auth_router

# Phase 4 - Onboarding
import onboarding
import onboarding_router

# Phase 4 - Resignation
import resignation
import resignation_router

# Phase 4 - Announcements
import announcements
import announcements_router

# Phase 4 - Tasks
import tasks
import tasks_routers as tasks_router

# Phase 4 - Integrations
import integrations

# Phase 4 - Feedback
import feedback
import feedback_router

# Phase 4 - Profile and Settings
import profile_router
import notification_preferences
import notification_preferences_router

# Create database tables
Base.metadata.create_all(bind=engine)

# FastAPI Application
app = FastAPI(
    title="WorkSphere HRMS",
    description="Smart HR Management System",
    version="4.0.0",
)
app.include_router(auth_router.router)


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

# Phase 4 - Employee Onboarding
app.include_router(onboarding_router.router)

# Phase 4 - Resignation Management
app.include_router(resignation_router.router)

# Phase 4 - Internal Announcements
app.include_router(announcements_router.router)

# Phase 4 - Task Assignment
app.include_router(tasks_router.router)

# Phase 4 - Third-Party Integrations
app.include_router(integrations.router)

# Phase 4 - Employee Feedback
app.include_router(feedback_router.router)

# Phase 4 - Profile & Settings
app.include_router(profile_router.router)

# Phase 4 - Notification Preferences
app.include_router(
    notification_preferences_router.router
)


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
