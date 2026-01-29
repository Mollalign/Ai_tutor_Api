"""
FastAPI Application Entry Point

This module initializes the FastAPI application with:
- CORS configuration
- Middleware setup
- Route registration
- Health check endpoints
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.db.database import check_db_connection
from app.db.redis import (
    check_redis_connection,
    get_redis_pool,
    close_redis_pool,
    close_arq_pool,
)
from app.db.vector_store import check_vector_store_health
from app.ai.rag import warmup_model
from app.middleware.logging import LoggingMiddleware
from app.api.v1.router import api_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================
# Application Lifespan Events
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    
    Startup:
    - Check database connection
    - Initialize Redis connection pool
    
    Shutdown:
    - Close Redis connections
    """
    # ========== STARTUP ==========
    logger.info(f"Starting {settings.PROJECT_NAME}...")
    logger.info(f"Debug mode: {settings.DEBUG}")
    
    # Check database connection on startup
    try:
        db_healthy = await check_db_connection()
        if db_healthy:
            logger.info("Database connection established successfully")
        else:
            logger.warning("Database connection check failed")
    except Exception as e:
        logger.error(f"Database connection error on startup: {e}")
    
    # Initialize Redis connection pool
    try:
        get_redis_pool()  # Creates the pool (singleton)
        redis_healthy = await check_redis_connection()
        if redis_healthy:
            logger.info("Redis connection established successfully")
        else:
            logger.warning("Redis connection check failed - background tasks may not work")
    except Exception as e:
        logger.error(f"Redis connection error on startup: {e}")
        # Don't fail startup - app can work without Redis (just no background tasks)

    try:
        model_info = warmup_model()
        logger.info(f"Embedding model loaded: {model_info['name']}")
    except Exception as e:
        logger.warning(f"Failed to warm up embedding model: {e}")    
    
    yield  # Application runs here
    
    # ========== SHUTDOWN ==========
    logger.info(f"Shutting down {settings.PROJECT_NAME}...")
    
    # Close Redis connections
    await close_redis_pool()
    await close_arq_pool()
    
    logger.info("Shutdown complete")


# ============================================================
# Create FastAPI Application
# ============================================================
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="""
    AI-Powered Educational Tutor API
    
    Features:
    - User Authentication (JWT)
    - Project Management
    - Document Upload & Processing
    - AI Chat with RAG
    - Quiz Generation
    - Progress Tracking
    """,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# ----------------------------------------------------
# Middleware Configuration
# ----------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

if settings.DEBUG:
    app.add_middleware(LoggingMiddleware)


# ----------------------------------------------------
# Health Check Endpoints
# ----------------------------------------------------
@app.get("/", tags=["Health"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": settings.PROJECT_NAME,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs" if settings.DEBUG else "disabled"
    }    



@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for monitoring.
    
    Checks:
    - Database connectivity
    - Redis connectivity
    - Vector store connectivity
    """
    try:
        db_healthy = await check_db_connection()
        redis_healthy = await check_redis_connection()
        vector_healthy = check_vector_store_health()
        
        status = "healthy"
        if not db_healthy or not redis_healthy:
            status = "degraded"
        if not vector_healthy:
            status = "degraded"
        
        return {
            "status": status,
            "database": "connected" if db_healthy else "disconnected",
            "redis": "connected" if redis_healthy else "disconnected",
            "vector_store": "connected" if vector_healthy else "disconnected",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "error": str(e)
            }
        ) 

# ============================================================
# Include API Router
# ============================================================
app.include_router(
    api_router,
    prefix=settings.API_V1_PREFIX
)


# ----------------------------------------------------
# Exception Handlers
# ----------------------------------------------------
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors."""
    return JSONResponse(
        status_code=404,
        content={"detail": "Not found"}
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Handle 500 errors."""
    logger.error(f"Internal server error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )