"""
Redis Connection Module

This module provides async Redis connection management for:
1. ARQ task queue (document processing)
2. Future: Caching, rate limiting, session storage

Redis is an in-memory data store that we use as a message broker
for background tasks. When a user uploads a file, we:
1. Save the file and create a DB record (fast, synchronous)
2. Push a task to Redis queue (instant)
3. Return response to user (total: ~100ms)

A separate worker process pulls tasks from Redis and processes them.
"""

import logging
from typing import Optional

from redis.asyncio import Redis, ConnectionPool
from arq.connections import RedisSettings, ArqRedis, create_pool

from app.core.config import settings

# ============================================================
# Logging Setup
# ============================================================
logger = logging.getLogger(__name__)

# ============================================================
# Redis Connection Pool (for general Redis operations)
# ============================================================

# Global connection pool - initialized once, reused everywhere
_redis_pool: Optional[ConnectionPool] = None

def get_redis_pool() -> ConnectionPool:
    """
    Get or create the Redis connection pool.
    
    Uses singleton pattern - creates pool once, reuses thereafter.
    This is called during app startup.
    """
    global _redis_pool

    if _redis_pool is None:
        _redis_pool = ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=10,      # Max simultaneous connections
            decode_responses=False,  # Return bytes (needed for some operations)
        )
        logger.info(f"Redis connection pool created: {settings.REDIS_URL}")
    
    return _redis_pool    


async def get_redis() -> Redis:
    """
    Dependency injection function for getting Redis client.
    
    Usage in FastAPI endpoints:
        @router.get("/")
        async def my_endpoint(redis: Redis = Depends(get_redis)):
            await redis.set("key", "value")
    """
    pool = get_redis_pool()
    return Redis(connection_pool=pool)    


async def close_redis_pool():
    """
    Close Redis connection pool during app shutdown.
    
    Called from FastAPI lifespan events to clean up resources.
    """
    global _redis_pool
    
    if _redis_pool is not None:
        await _redis_pool.disconnect()
        _redis_pool = None
        logger.info("Redis connection pool closed")


# ============================================================
# ARQ Redis Settings (for task queue)
# ============================================================

def get_arq_redis_settings() -> RedisSettings:
    """
    Get Redis settings for ARQ task queue.
    
    ARQ uses its own RedisSettings class that parses the URL
    and extracts host, port, database, and password.
    
    Returns:
        RedisSettings configured from REDIS_URL
    """
    # Parse Redis URL components
    # Format: redis://[[username]:[password]@]host[:port][/db-number]
    url = settings.REDIS_URL
    
    # RedisSettings can parse a URL directly
    # But we'll be explicit for clarity
    
    # Default values
    host = "localhost"
    port = 6379
    database = 0
    password = None

    # Parse URL if it starts with redis://
    if url.startswith("redis://"):
        # Remove protocol prefix
        url_parts = url.replace("redis://", "")
        
        # Check for password
        if "@" in url_parts:
            auth, url_parts = url_parts.split("@", 1)
            if ":" in auth:
                _, password = auth.split(":", 1)
            else:
                password = auth
        
        # Check for database number
        if "/" in url_parts:
            url_parts, db_str = url_parts.rsplit("/", 1)
            try:
                database = int(db_str)
            except ValueError:
                database = 0
        
        # Parse host:port
        if ":" in url_parts:
            host, port_str = url_parts.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 6379
        else:
            host = url_parts or "localhost"

    return RedisSettings(
        host=host,
        port=port,
        database=database,
        password=password,
        # Connection retry settings
        conn_timeout=10,       # Timeout for initial connection (seconds)
        conn_retries=5,        # Number of retry attempts
        conn_retry_delay=1,    # Delay between retries (seconds)
    )  

# ============================================================
# ARQ Connection Pool (for enqueueing tasks)
# ============================================================
# This is used by your FastAPI app to add tasks to the queue.
# The worker process will pick them up and execute them.
# ============================================================ 
 
_arq_pool: Optional[ArqRedis] = None


async def get_arq_pool() -> ArqRedis:
    """
    Get or create the ARQ Redis pool for enqueueing tasks.
    
    Usage:
        pool = await get_arq_pool()
        await pool.enqueue_job('process_document', document_id=doc_id)
    """
    global _arq_pool
    
    if _arq_pool is None:
        _arq_pool = await create_pool(get_arq_redis_settings())
        logger.info("ARQ Redis pool created")
    
    return _arq_pool


async def close_arq_pool():
    """Close ARQ Redis pool during shutdown."""
    global _arq_pool
    
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None
        logger.info("ARQ Redis pool closed")

# ============================================================
# Health Check
# ============================================================

async def check_redis_connection() -> bool:
    """
    Check if Redis is reachable.
    
    Used for health checks and startup verification.
    
    Returns:
        True if Redis responds to PING, False otherwise
    """
    try:
        redis = await get_redis()
        # PING command - Redis should respond with PONG
        response = await redis.ping()
        logger.info("Redis health check: OK")
        return response
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        return False