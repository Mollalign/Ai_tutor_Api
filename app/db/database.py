import ssl 
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import text

from ..core.config import settings

# ----------------------------------------------------
# Logging
# ----------------------------------------------------
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Base for all ORM models
Base = declarative_base()

# ----------------------------------------------------
# SSL Configuration (Neon/Postgres Cloud)
# ----------------------------------------------------
def build_ssl_context():
    """
    Build SSL context for Neon or any cloud PostgreSQL provider
    requiring encrypted connections.
    """
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = True
    ssl_context.verify_mode = ssl.CERT_REQUIRED
    return ssl_context

# ----------------------------------------------------
# Engine Configuration
# ----------------------------------------------------
def build_engine():
    # Cloud PostgreSQL (Neon)
    ssl_context = build_ssl_context()

    engine_kwargs = {
        "echo": settings.DEBUG,
        "future": True,
        "pool_size": 10,
        "max_overflow": 5,
        "pool_timeout": 30,
        "pool_pre_ping": True,
        "pool_recycle": 3600,  # refresh connections every hour
        "connect_args": {
            "ssl": ssl_context,
            "server_settings": {
                "application_name": settings.PROJECT_NAME,
            }
        },
    }

    # Remove SSL parameters from URL if included
    clean_url = settings.DATABASE_URL.unicode_string().split("?")[0]
    
    return create_async_engine(clean_url, **engine_kwargs)


# Create global engine
engine = build_engine()


# ----------------------------------------------------
# Session Factory
# ----------------------------------------------------
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ----------------------------------------------------
# Dependency for framework routes/services
# ----------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides an async database session for each request.
    Ensures session is closed cleanly after use.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ----------------------------------------------------
# Database Utilities
# ----------------------------------------------------
async def init_db():
    """
    Create all database tables.
    Should be called only in development/testing,
    not in production environments with migrations.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully.")


async def drop_all_tables():
    """
    Drops all tables — dangerous. Use only in development.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.warning("All tables dropped.")


async def check_db_connection() -> bool:
    """
    Performs a health check using SELECT 1.
    Useful for monitoring, readyness/liveness probes, etc.
    """
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            row = result.first()
        logger.info("Database connection healthy.")
        return row is not None
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


async def invalidate_connection_pool():
    """
    Clears all cached prepared statements after database schema changes.
    Use after Alembic migrations without restarting app.
    """
    logger.info("Invalidating connection pool...")
    await engine.dispose()
    logger.info("Connection pool invalidated.")


async def create_db_extensions():
    """
    Ensure PostgreSQL extensions required by Finance Tracker exist.
    UUID and crypto extensions are used in JWT, password hashing,
    ID generation and secure fields.
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'))
            await conn.execute(text('CREATE EXTENSION IF NOT EXISTS pgcrypto;'))
        logger.info("PostgreSQL extensions created successfully.")
    except Exception as e:
        logger.error(f"Extension creation failed: {e}")


# ----------------------------------------------------
# Management API for DevOps Scripts
# ----------------------------------------------------
class DatabaseManager:
    @staticmethod
    async def initialize():
        """Initialize DB + extensions (dev only)."""
        await init_db()
        await create_db_extensions()
        logger.info("Database initialization complete.")

    @staticmethod
    async def health_check() -> bool:
        return await check_db_connection()

    @staticmethod
    async def invalidate_pool():
        await invalidate_connection_pool()
