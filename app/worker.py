"""
ARQ Worker Configuration

This module configures the ARQ background worker.

Running the Worker:
------------------
    # From project root directory
    arq app.worker.WorkerSettings
    
    # With verbose logging
    arq app.worker.WorkerSettings --verbose
    
    # With custom log level
    ARQ_LOG_LEVEL=DEBUG arq app.worker.WorkerSettings

Worker Lifecycle:
----------------
1. Worker starts and connects to Redis
2. Worker calls startup() function
3. Worker polls Redis for jobs
4. For each job, worker calls the corresponding function
5. On shutdown, worker calls shutdown() function

Scaling Workers:
---------------
You can run multiple workers for parallel processing:
    
    # Terminal 1
    arq app.worker.WorkerSettings
    
    # Terminal 2
    arq app.worker.WorkerSettings
    
    # Terminal 3
    arq app.worker.WorkerSettings

Each worker will pull jobs from the same Redis queue.
Jobs are distributed across workers automatically.
"""

import logging
from typing import Any, Dict, Optional

from arq import cron
from arq.connections import RedisSettings

from app.db.redis import get_arq_redis_settings
from app.tasks.document_tasks import process_document

# ============================================================
# Logging Configuration
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================
# Startup and Shutdown Hooks
# ============================================================

async def startup(ctx: Dict[str, Any]) -> None:
    """
    Called when worker starts.
    
    We pre-load the embedding model here so:
    - First document doesn't have cold-start delay
    - Model is loaded once, not per job
    - Any loading errors are caught early
    """
    logger.info("ARQ Worker starting up...")
    
    # ================================================
    # Pre-load the embedding model
    # ================================================
    # This avoids cold-start on first document
    try:
        from app.ai.rag.embedder import warmup_model
        model_info = warmup_model()
        logger.info(f"Embedding model loaded: {model_info['name']}")
        
        # Store model info in context (optional, for reference)
        ctx['embedding_model'] = model_info['name']
        ctx['embedding_dimension'] = model_info['dimension']
        
    except Exception as e:
        logger.warning(f"Failed to pre-load embedding model: {e}")
        logger.warning("Model will be loaded on first use (slower)")
    
    # ================================================
    # Initialize vector store connection
    # ================================================
    try:
        from app.db.vector_store import get_chroma_client
        get_chroma_client()  # Initialize the singleton
        logger.info("Vector store (ChromaDB) initialized")
    except Exception as e:
        logger.warning(f"Vector store initialization warning: {e}")
    
    logger.info(" ARQ Worker ready to process jobs")


async def shutdown(ctx: Dict[str, Any]) -> None:
    """
    Called when worker shuts down.
    
    Clean up resources.
    """
    logger.info("ARQ Worker shutting down...")
    
    # Reset singletons to free memory
    try:
        from app.db.vector_store import reset_vector_store
        reset_vector_store()
    except Exception as e:
        logger.debug(f"Vector store cleanup: {e}")
    
    logger.info("ARQ Worker shutdown complete")


# ============================================================
# Worker Configuration Class
# ============================================================

class WorkerSettings:
    """
    ARQ Worker settings.
    
    This class is discovered by ARQ when you run:
        arq app.worker.WorkerSettings
    """
    
    # ========================================
    # Task Functions
    # ========================================
    functions = [
        process_document,
    ]
    
    # ========================================
    # Redis Connection
    # ========================================
    redis_settings = get_arq_redis_settings()
    
    # ========================================
    # Lifecycle Hooks
    # ========================================
    on_startup = startup
    on_shutdown = shutdown
    
    # ========================================
    # Job Settings
    # ========================================
    job_timeout = 600      # 10 minutes (for large documents)
    keep_result = 3600     # 1 hour
    max_tries = 3          # Retry failed jobs up to 3 times
    retry_delay = 60       # 1 minute base delay between retries
    
    # ========================================
    # Concurrency Settings
    # ========================================
    max_jobs = 5           # Process up to 5 documents in parallel
    poll_delay = 0.5       # Check for new jobs every 0.5 seconds
    
    # ========================================
    # Queue Settings
    # ========================================
    queue_name = "arq:queue"
    health_check_interval = 10