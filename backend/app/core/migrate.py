"""Bring the database structure up to date when the app starts.

Each change to the database structure is a numbered step ("migration") in
app/migrations/versions. The database remembers which step it is at, and
only the missing steps are applied. Existing data is kept.
"""

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import engine

# MIGRATIONS_V1

_MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "migrations",
)
# The step that matches a database built before migrations existed.
_BASELINE = "0001"


def run_migrations() -> None:
    config = Config()
    config.set_main_option("script_location", _MIGRATIONS_DIR)

    tables = set(inspect(engine).get_table_names())

    if "alembic_version" not in tables and "projects" in tables:
        # An older database: its tables are already there, so only record
        # that it is at the baseline step.
        command.stamp(config, _BASELINE)

    command.upgrade(config, "head")
