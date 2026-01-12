"""
Base Model Module

This module provides a base class for all SQLAlchemy models with common fields:
- id: Primary key (UUID)
- created_at: Timestamp when record was created
- updated_at: Timestamp when record was last update
"""

import uuid
from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import UUID

# Import the Base from your database module
from app.db.database import Base


class BaseModel(Base):
    """
    Abstract base model class that provides common fields for all models.
    
    Attributes:
        id (UUID): Primary key, auto-generated UUID
        created_at (DateTime): Timestamp set automatically when record is created
        updated_at (DateTime): Timestamp updated automatically when record is modified
    
    """
    
    # This makes the class abstract - no table will be created for BaseModel itself
    __abstract__ = True
    
    # Primary Key - UUID for better security and distributed systems
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,  
        server_default=func.gen_random_uuid(),  
        nullable=False,
        index=True
    )
    
    # Created timestamp - set once when record is created
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),  
        nullable=False
    )
    
    # Updated timestamp - updates every time the record is modified
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(), 
        onupdate=func.now(),  
        nullable=False
    )
    
    def __repr__(self):
        """String representation for debugging."""
        return f"<{self.__class__.__name__}(id={self.id})>"
