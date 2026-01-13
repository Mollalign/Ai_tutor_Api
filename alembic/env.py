from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import sys
from pathlib import Path

# ============================================================
# Add app directory to Python path
# ============================================================
# This allows Alembic to import your app modules
# ============================================================
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.database import Base

# Import ALL your models here so Alembic knows about them
from app.models.user import User
from app.models.project import Project
from app.models.document import Document
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.topic import Topic, Subtopic
from app.models.knowledge_state import KnowledgeState
from app.models.quiz import Quiz
from app.models.quiz_question import QuizQuestion
from app.models.quiz_attempt import QuizAttempt
from app.models.quiz_response import QuizResponse
from app.models.password_reset import PasswordReset

# ============================================================
# Alembic Config
# ============================================================

config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate
target_metadata = Base.metadata

# Set the database URL from our settings
config.set_main_option("sqlalchemy.url", str(settings.DATABASE_URL))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Convert asyncpg URL to psycopg2 for Alembic (synchronous)
    # Alembic needs a synchronous driver
    database_url = str(settings.DATABASE_URL)
    if database_url.startswith("postgresql+asyncpg://"):
        # Replace asyncpg with psycopg2 for Alembic
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    # Create synchronous engine for Alembic
    connectable = engine_from_config(
        {"sqlalchemy.url": database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()