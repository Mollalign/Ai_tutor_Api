"""
Notification Service

Sends push notifications via Firebase Cloud Messaging (FCM) and
persists them to the database for in-app viewing.
"""

import logging
from typing import Optional
from uuid import UUID

import firebase_admin
from firebase_admin import credentials, messaging

from app.core.config import settings

logger = logging.getLogger(__name__)

_firebase_initialized = False


def _ensure_firebase():
    """Initialize Firebase Admin SDK once."""
    global _firebase_initialized
    if _firebase_initialized:
        return
    try:
        key_path = getattr(settings, "FIREBASE_SERVICE_ACCOUNT_KEY_PATH", None)
        if key_path:
            cred = credentials.Certificate(key_path)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()
        _firebase_initialized = True
        logger.info("Firebase Admin SDK initialized")
    except Exception as e:
        logger.warning("Firebase Admin SDK init failed (notifications disabled): %s", e)


async def save_notification(
    db,
    user_id: UUID,
    title: str,
    body: str,
    notification_type: str = "general",
):
    """Persist a notification to the database."""
    from app.models.notification import Notification as NotificationModel
    notif = NotificationModel(
        user_id=user_id,
        title=title,
        body=body,
        type=notification_type,
    )
    db.add(notif)
    await db.commit()


async def save_study_notification(
    db,
    user_id: UUID,
    title: str,
    body: str,
):
    """Save a study-related notification."""
    await save_notification(db, user_id, title, body, "study_reminder")


async def send_push_notification(
    fcm_token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> bool:
    """Send a push notification to a single device."""
    _ensure_firebase()
    if not _firebase_initialized:
        return False

    try:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            token=fcm_token,
        )
        messaging.send(message)
        logger.info("Push sent to token %s...", fcm_token[:20])
        return True
    except messaging.UnregisteredError:
        logger.warning("FCM token expired/unregistered: %s...", fcm_token[:20])
        return False
    except Exception as e:
        logger.error("Failed to send push: %s", e)
        return False


async def send_quiz_result_notification(
    fcm_token: Optional[str],
    quiz_title: str,
    score_pct: float,
    passed: bool,
    db=None,
    user_id: Optional[UUID] = None,
):
    """Send a notification about quiz completion and save to DB."""
    result_label = "Pass" if passed else "Keep trying"
    title = f"Quiz Complete: {quiz_title}"
    body = f"You scored {score_pct:.0f}% - {result_label}!"

    # Save to database for in-app notification list
    if db and user_id:
        try:
            await save_notification(db, user_id, title, body, "quiz_result")
        except Exception as e:
            logger.warning("Failed to save notification to DB: %s", e)

    # Send push notification
    if fcm_token:
        await send_push_notification(
            fcm_token=fcm_token,
            title=title,
            body=body,
            data={"type": "quiz_result", "quiz_title": quiz_title},
        )
