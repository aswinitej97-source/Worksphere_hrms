import sqlite3
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from database import Base, engine
import models


REQUIRED_TABLES = {
    "users",
    "employees",
    "attendance",
    "leaves",
    "payroll",
    "notifications",
}


def get_columns(connection, table_name):
    rows = connection.exec_driver_sql(
        f'PRAGMA table_info("{table_name}")'
    ).fetchall()

    return {row[1] for row in rows}


def add_column(
    connection,
    table_name,
    column_name,
    definition,
):
    columns = get_columns(connection, table_name)

    if column_name in columns:
        print(f"Already exists: {table_name}.{column_name}")
        return

    connection.exec_driver_sql(
        f'ALTER TABLE "{table_name}" '
        f'ADD COLUMN "{column_name}" {definition}'
    )

    print(f"Added: {table_name}.{column_name}")


def create_backup(db_path):
    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    backup_path = db_path.with_name(
        f"{db_path.stem}_phase2_backup_{timestamp}.db"
    )

    with sqlite3.connect(str(db_path)) as source:
        with sqlite3.connect(str(backup_path)) as target:
            source.backup(target)

    print(f"Backup created: {backup_path.name}")


def initialize_missing_balances(connection):
    # Existing balances are preserved.
    # New balances account for already-approved leave.
    policies = connection.execute(
        select(
            models.LeavePolicy.id,
            models.LeavePolicy.leave_type,
            models.LeavePolicy.total_days_allowed,
        )
    ).mappings().all()

    employee_ids = connection.execute(
        select(models.Employee.id)
    ).scalars().all()

    created = 0

    for policy in policies:
        for employee_id in employee_ids:
            existing_id = connection.execute(
                select(models.LeaveBalance.id).where(
                    models.LeaveBalance.employee_id == employee_id,
                    models.LeaveBalance.leave_type
                    == policy["leave_type"],
                )
            ).scalar_one_or_none()

            if existing_id is not None:
                continue

            approved_leaves = connection.execute(
                select(
                    models.Leave.start_date,
                    models.Leave.end_date,
                ).where(
                    models.Leave.employee_id == employee_id,
                    models.Leave.leave_type == policy["leave_type"],
                    models.Leave.status
                    == models.LeaveStatus.APPROVED,
                )
            ).all()

            used_days = sum(
                (end_date - start_date).days + 1
                for start_date, end_date in approved_leaves
            )

            allowed = policy["total_days_allowed"]

            if used_days > allowed:
                print(
                    f"Note: employee {employee_id}, "
                    f"{policy['leave_type'].value}: "
                    "historical approved leave exceeds allowance. "
                    "Starting remaining balance at zero."
                )

            connection.execute(
                models.LeaveBalance.__table__.insert().values(
                    employee_id=employee_id,
                    leave_type=policy["leave_type"],
                    remaining_days=max(allowed - used_days, 0),
                )
            )

            created += 1

    print(f"Missing leave balances created: {created}")

    if not policies:
        print(
            "No leave policies configured yet. "
            "HR/Admin can create them after setup."
        )


def migrate():
    if engine.dialect.name != "sqlite":
        raise RuntimeError(
            "This migration is for the project's SQLite database."
        )

    database_name = engine.url.database

    if not database_name or database_name == ":memory:":
        raise RuntimeError("A file-based SQLite database is required.")

    db_path = Path(database_name).resolve()

    if not db_path.is_file():
        raise RuntimeError(
            f"Database not found: {db_path}\n"
            "Run this script from the worksphere_hrms folder."
        )

    # Read-only preflight: reject an unrelated or incomplete database.
    with sqlite3.connect(str(db_path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table'"
            ).fetchall()
        }

    missing = REQUIRED_TABLES - tables

    if missing:
        raise RuntimeError(
            "Required Phase 1 tables are missing: "
            + ", ".join(sorted(missing))
        )

    create_backup(db_path)

    with engine.connect() as connection:
        # Explicit BEGIN makes the schema changes transactional
        # with SQLite's default Python driver behavior.
        connection.exec_driver_sql("BEGIN IMMEDIATE")

        try:
            add_column(
                connection,
                "users",
                "is_active",
                "BOOLEAN NOT NULL DEFAULT 1",
            )

            add_column(
                connection,
                "attendance",
                "is_late",
                "BOOLEAN NOT NULL DEFAULT 0",
            )

            add_column(
                connection,
                "attendance",
                "late_minutes",
                "INTEGER NOT NULL DEFAULT 0 "
                "CHECK (late_minutes >= 0)",
            )

            add_column(
                connection,
                "payroll",
                "allowances",
                "NUMERIC(12, 2) NOT NULL DEFAULT 0 "
                "CHECK (allowances >= 0)",
            )

            # Creates missing tables and their indexes/constraints.
            # It does not rebuild existing Phase 1 tables.
            Base.metadata.create_all(bind=connection)

            initialize_missing_balances(connection)

            required_columns = {
                "users": {"is_active"},
                "attendance": {"is_late", "late_minutes"},
                "payroll": {"allowances"},
                "leave_policies": {
                    "id",
                    "leave_type",
                    "total_days_allowed",
                },
                "leave_balances": {
                    "id",
                    "employee_id",
                    "leave_type",
                    "remaining_days",
                },
            }

            for table_name, expected in required_columns.items():
                actual = get_columns(connection, table_name)
                absent = expected - actual

                if absent:
                    raise RuntimeError(
                        f"Migration verification failed for "
                        f"{table_name}: {sorted(absent)}"
                    )

            connection.commit()

        except Exception:
            connection.rollback()
            print("Migration failed. Changes rolled back.")
            raise

    print()
    print("SUCCESS: Phase 2 database migration completed.")
    print("Existing users and HR records preserved.")
    print(
        "Historical attendance keeps default late values; "
        "new check-ins will calculate lateness."
    )
    print(
        "Existing payroll keeps its original amounts, "
        "with allowances defaulting to zero."
    )


if __name__ == "__main__":
    migrate()