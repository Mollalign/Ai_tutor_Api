from sqlalchemy import Column, String, Boolean, ForeignKey, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from .base import BaseModel


class NotificationPreference(BaseModel):
    __tablename__ = "notification_preferences"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    study_reminders_enabled = Column(Boolean, default=False, nullable=False)
    reminder_time = Column(Time, nullable=True)  # e.g. 09:00 for daily reminder
    quiz_results_enabled = Column(Boolean, default=True, nullable=False)

    user = relationship("User", backref="notification_preference")
