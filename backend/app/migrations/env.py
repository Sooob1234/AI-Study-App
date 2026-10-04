"""Alembic environment: tells the migration tool how to reach the database."""

from alembic import context

from app.core.database import Base, engine

# Importing the models registers every table on Base.metadata.
from app.models import (  # noqa: F401
    project,
    source,
    source_chunk,
    source_page,
    source_segment,
    output,
    user,
)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
