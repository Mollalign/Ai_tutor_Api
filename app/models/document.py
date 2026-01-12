from sqlalchemy import Column, String, Integer, BigInteger, ForeignKey, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from .base import BaseModel

class Document(BaseModel):
    __tablename__ = "documents"
    
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)  # Stored filename
    original_filename = Column(String(255), nullable=False)  # User's original filename
    file_type = Column(String(20), nullable=False)  # pdf, pptx, docx, txt
    file_path = Column(String(500), nullable=False)  # Storage path
    file_size = Column(BigInteger, nullable=False)  # Size in bytes
    status = Column(String(20), default="pending", nullable=False)  # pending, processing, ready, failed
    error_message = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="documents")