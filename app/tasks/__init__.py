"""
Background Tasks Module

This module contains all background task definitions for ARQ workers.

Task Organization:
-----------------
- document_tasks.py: Document processing (parsing, embedding)
- Future: email_tasks.py, notification_tasks.py, etc.

How Tasks Work:
--------------
1. FastAPI app enqueues a job: await pool.enqueue_job('task_name', arg=value)
2. Redis stores the job in a queue
3. ARQ worker polls Redis and picks up the job
4. Worker executes the task function
5. Result (or error) is stored back in Redis

Task functions receive a special `ctx` parameter:
- ctx['redis']: Redis connection for the worker
- ctx['job_id']: Unique ID of this job
- ctx['job_try']: Which retry attempt this is (1, 2, 3...)

Running Workers:
---------------
    # Start a worker (from project root)
    arq app.worker.WorkerSettings

    # With logging
    arq app.worker.WorkerSettings --verbose
"""

from app.tasks.document_tasks import process_document

# Export all task functions
# These names are used when enqueueing: enqueue_job('process_document', ...)
__all__ = [
    "process_document",
]