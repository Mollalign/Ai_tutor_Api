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
# Code that runs on startup and shutdown
# ============================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    
    Startup:
    - Initialize database extensions if needed
    
    Shutdown:
    - Clean up resources
    """
    # Startup
    logger.info(f"Starting {settings.PROJECT_NAME}...")
    logger.info(f"Debug mode: {settings.DEBUG}")
    
    # Check database connection on startup
    try:
        is_healthy = await check_db_connection()
        if is_healthy:
            logger.info("Database connection established successfully")
        else:
            logger.warning("Database connection check failed")
    except Exception as e:
        logger.error(f"Database connection error on startup: {e}")
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.PROJECT_NAME}...")


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
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
    lifespan=lifespan
)

# ----------------------------------------------------
# Middleware Configuration
# ----------------------------------------------------

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Logging Middleware
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
    """Health check endpoint for monitoring."""
    try:
        db_healthy = await check_db_connection()
        return {
            "status": "healthy" if db_healthy else "degraded",
            "database": "connected" if db_healthy else "disconnected"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "database": "error",
                "error": str(e)
            }
        )    
    

# ============================================================
# Include API Router
# ============================================================
# All routes under /api/v1
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