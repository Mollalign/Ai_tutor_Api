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
# Configure logging for the worker process

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
    
    Use this for:
    - Initializing connections
    - Loading models into memory
    - Setting up resources shared across jobs
    
    The ctx dict can store values that will be available to all jobs.
    
    Args:
        ctx: Worker context dictionary (shared across all jobs)
    
    Example:
        async def startup(ctx):
            # Load ML model once (not for each job)
            ctx['model'] = load_model()
        
        async def my_task(ctx, data):
            model = ctx['model']  # Use pre-loaded model
    """
    logger.info("🚀 ARQ Worker starting up...")
    
    # Initialize any shared resources here
    # For example, when you add vector database:
    # ctx['vector_store'] = await initialize_vector_store()
    
    logger.info("✅ ARQ Worker ready to process jobs")


async def shutdown(ctx: Dict[str, Any]) -> None:
    """
    Called when worker shuts down.
    
    Use this for:
    - Closing connections
    - Releasing resources
    - Cleanup operations
    
    Args:
        ctx: Worker context dictionary
    """
    logger.info("🛑 ARQ Worker shutting down...")
    
    # Close any shared resources here
    # For example:
    # if 'vector_store' in ctx:
    #     await ctx['vector_store'].close()
    
    logger.info("👋 ARQ Worker shutdown complete")


# ============================================================
# Worker Configuration Class
# ============================================================

class WorkerSettings:
    """
    ARQ Worker settings.
    
    This class is discovered by ARQ when you run:
        arq app.worker.WorkerSettings
    
    ARQ looks for these attributes:
    - functions: List of task functions
    - redis_settings: How to connect to Redis
    - on_startup: Function to call on start
    - on_shutdown: Function to call on stop
    - And many optional settings...
    """
    
    # ========================================
    # Task Functions
    # ========================================
    # List all functions that can be called as background tasks
    # The function name becomes the job name for enqueue_job()
    
    functions = [
        process_document,
        # Future tasks:
        # send_email,
        # generate_quiz,
        # update_progress,
    ]
    
    # ========================================
    # Redis Connection
    # ========================================
    # How to connect to Redis
    # Uses our helper function from redis.py
    
    redis_settings = get_arq_redis_settings()
    
    # ========================================
    # Lifecycle Hooks
    # ========================================
    
    on_startup = startup
    on_shutdown = shutdown
    
    # ========================================
    # Job Settings
    # ========================================
    
    # Maximum time a job can run before being killed (in seconds)
    # Document processing might take a while for large files
    job_timeout = 600  # 10 minutes
    
    # How long to keep job results in Redis (in seconds)
    # Results can be retrieved with job.result()
    keep_result = 3600  # 1 hour
    
    # Maximum number of times to retry a failed job
    # Set to 0 to disable retries
    max_tries = 3
    
    # Time to wait between retries (in seconds)
    # This is a base value - actual delay increases exponentially
    retry_delay = 60  # 1 minute base delay
    
    # ========================================
    # Concurrency Settings
    # ========================================
    
    # Maximum number of jobs to run concurrently
    # Higher = more parallel processing
    # Lower = less memory usage
    max_jobs = 5
    
    # Seconds to wait when queue is empty before checking again
    poll_delay = 0.5
    
    # ========================================
    # Queue Settings
    # ========================================
    
    # Name of the default queue
    # You can have multiple queues for priority
    queue_name = "arq:queue"
    
    # ========================================
    # Health Check (Optional)
    # ========================================
    
    # Enable health check endpoint
    # Workers will respond to PING with PONG
    health_check_interval = 10  # seconds
    
    # ========================================
    # Cron Jobs (Optional)
    # ========================================
    # Scheduled tasks that run periodically
    # Uncomment to enable periodic cleanup
    
    # cron_jobs = [
    #     cron(cleanup_old_files, hour=3, minute=0),  # Run at 3 AM daily
    # ]


# ============================================================
# Optional: Cron Job Example
# ============================================================

async def cleanup_old_files(ctx: Dict[str, Any]) -> None:
    """
    Example cron job: Clean up temporary files.
    
    Cron jobs are scheduled tasks that run at specific times.
    Unlike regular jobs, they're not triggered by enqueue_job().
    
    To enable:
    1. Uncomment the cron_jobs line in WorkerSettings
    2. Import cron from arq
    
    Args:
        ctx: Worker context
    """
    logger.info("Running scheduled cleanup...")
    # TODO: Implement cleanup logic
    pass