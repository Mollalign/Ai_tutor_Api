"""
WebSocket Manager

Manages real-time WebSocket connections for chat functionality.
Uses Redis Pub/Sub for cross-instance message broadcasting.

This enables:
- Real-time message delivery to connected clients
- Multi-instance support (multiple backend servers)
- Automatic reconnection handling
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional, Any
from uuid import UUID
from dataclasses import dataclass, asdict
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from app.db.redis import get_redis

logger = logging.getLogger(__name__)


# ============================================================
# Message Types
# ============================================================

@dataclass
class WebSocketMessage:
    """Base WebSocket message structure."""
    type: str
    conversation_id: str
    data: Dict[str, Any]
    timestamp: str = ""
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()
    
    def to_json(self) -> str:
        return json.dumps(asdict(self))
    
    @classmethod
    def from_json(cls, data: str) -> "WebSocketMessage":
        parsed = json.loads(data)
        return cls(**parsed)


class MessageTypes:
    """WebSocket message type constants."""
    NEW_MESSAGE = "new_message"          # New message added to conversation
    MESSAGE_UPDATED = "message_updated"  # Message content updated (e.g., streaming complete)
    TYPING = "typing"                    # User is typing
    CONNECTED = "connected"              # Connection established
    ERROR = "error"                      # Error occurred


# ============================================================
# Connection Manager
# ============================================================

class ConnectionManager:
    """
    Manages WebSocket connections for all users/conversations.
    
    Features:
    - Per-conversation connection tracking
    - Per-user connection tracking
    - Redis Pub/Sub for cross-instance broadcasting
    """
    
    def __init__(self):
        # Map: conversation_id -> Set of WebSocket connections
        self._conversation_connections: Dict[str, Set[WebSocket]] = {}
        
        # Map: user_id -> Set of WebSocket connections (for user-specific messages)
        self._user_connections: Dict[str, Set[WebSocket]] = {}
        
        # Map: WebSocket -> (user_id, conversation_id) for cleanup
        self._connection_info: Dict[WebSocket, tuple] = {}
        
        # Redis subscription task
        self._redis_subscriber_task: Optional[asyncio.Task] = None
        self._redis: Optional[Redis] = None
        
    # ============================================================
    # Connection Management
    # ============================================================
    
    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        conversation_id: str
    ) -> None:
        """
        Accept and register a new WebSocket connection.
        
        Args:
            websocket: The WebSocket connection
            user_id: User's UUID string
            conversation_id: Conversation UUID string
        """
        await websocket.accept()
        
        # Track by conversation
        if conversation_id not in self._conversation_connections:
            self._conversation_connections[conversation_id] = set()
        self._conversation_connections[conversation_id].add(websocket)
        
        # Track by user
        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(websocket)
        
        # Store connection info for cleanup
        self._connection_info[websocket] = (user_id, conversation_id)
        
        logger.info(
            f"WebSocket connected: user={user_id}, conversation={conversation_id}. "
            f"Total connections for conversation: {len(self._conversation_connections[conversation_id])}"
        )
        
        # Send connection confirmation
        await self._send_to_socket(websocket, WebSocketMessage(
            type=MessageTypes.CONNECTED,
            conversation_id=conversation_id,
            data={"user_id": user_id, "status": "connected"}
        ))
        
        # Start Redis subscriber if not running
        await self._ensure_redis_subscriber()
    
    def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove a WebSocket connection from all tracking.
        
        Args:
            websocket: The disconnecting WebSocket
        """
        if websocket not in self._connection_info:
            return
        
        user_id, conversation_id = self._connection_info[websocket]
        
        # Remove from conversation tracking
        if conversation_id in self._conversation_connections:
            self._conversation_connections[conversation_id].discard(websocket)
            if not self._conversation_connections[conversation_id]:
                del self._conversation_connections[conversation_id]
        
        # Remove from user tracking
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(websocket)
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]
        
        # Remove connection info
        del self._connection_info[websocket]
        
        logger.info(f"WebSocket disconnected: user={user_id}, conversation={conversation_id}")
    
    # ============================================================
    # Message Broadcasting
    # ============================================================
    
    async def broadcast_to_conversation(
        self,
        conversation_id: str,
        message: WebSocketMessage
    ) -> None:
        """
        Broadcast a message to all connections in a conversation.
        Uses Redis Pub/Sub for cross-instance delivery.
        
        Args:
            conversation_id: Target conversation UUID string
            message: The message to broadcast
        """
        channel = f"chat:{conversation_id}"
        
        try:
            redis = await get_redis()
            await redis.publish(channel, message.to_json())
            logger.info(f"Published message to Redis channel {channel}")
        except Exception as e:
            logger.error(f"Failed to publish to Redis: {e}")
            # Fallback to direct delivery for local connections
            await self._deliver_to_conversation_local(conversation_id, message)
    
    async def _deliver_to_conversation_local(
        self,
        conversation_id: str,
        message: WebSocketMessage
    ) -> None:
        """
        Deliver message to local WebSocket connections only.
        Used as fallback when Redis is unavailable.
        """
        connections = self._conversation_connections.get(conversation_id, set())
        
        if not connections:
            logger.debug(f"No local connections for conversation {conversation_id}")
            return
        
        # Send to all connections, handling failures gracefully
        disconnected = []
        for websocket in connections:
            try:
                await self._send_to_socket(websocket, message)
            except Exception as e:
                logger.warning(f"Failed to send to websocket: {e}")
                disconnected.append(websocket)
        
        # Clean up disconnected sockets
        for ws in disconnected:
            self.disconnect(ws)
    
    async def _send_to_socket(
        self,
        websocket: WebSocket,
        message: WebSocketMessage
    ) -> None:
        """Send a message to a specific WebSocket."""
        await websocket.send_text(message.to_json())
    
    # ============================================================
    # Redis Pub/Sub Subscriber
    # ============================================================
    
    async def _ensure_redis_subscriber(self) -> None:
        """Ensure Redis subscriber is running."""
        if self._redis_subscriber_task is None or self._redis_subscriber_task.done():
            self._redis_subscriber_task = asyncio.create_task(
                self._redis_subscriber_loop()
            )
            logger.info("Started Redis Pub/Sub subscriber task")
    
    async def _redis_subscriber_loop(self) -> None:
        """
        Background task that subscribes to Redis channels and delivers messages.
        Uses pattern subscription to handle all conversation channels.
        """
        try:
            redis = await get_redis()
            pubsub = redis.pubsub()
            
            # Subscribe to pattern: chat:* (all conversation channels)
            await pubsub.psubscribe("chat:*")
            logger.info("Subscribed to Redis pattern: chat:*")
            
            async for message in pubsub.listen():
                if message["type"] == "pmessage":
                    try:
                        # Extract conversation_id from channel name (chat:<uuid>)
                        channel = message["channel"]
                        if isinstance(channel, bytes):
                            channel = channel.decode("utf-8")
                        conversation_id = channel.split(":", 1)[1]
                        
                        # Parse and deliver message
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode("utf-8")
                        
                        ws_message = WebSocketMessage.from_json(data)
                        await self._deliver_to_conversation_local(
                            conversation_id, 
                            ws_message
                        )
                    except Exception as e:
                        logger.error(f"Error processing Redis message: {e}")
        
        except asyncio.CancelledError:
            logger.info("Redis subscriber task cancelled")
            raise
        except Exception as e:
            logger.error(f"Redis subscriber error: {e}")
            # Wait before retrying
            await asyncio.sleep(5)
            await self._ensure_redis_subscriber()
    
    async def shutdown(self) -> None:
        """Gracefully shutdown the connection manager."""
        if self._redis_subscriber_task:
            self._redis_subscriber_task.cancel()
            try:
                await self._redis_subscriber_task
            except asyncio.CancelledError:
                pass
        
        # Close all WebSocket connections
        for websocket in list(self._connection_info.keys()):
            try:
                await websocket.close()
            except Exception:
                pass
        
        self._conversation_connections.clear()
        self._user_connections.clear()
        self._connection_info.clear()
        
        logger.info("WebSocket ConnectionManager shutdown complete")


# ============================================================
# Singleton Instance
# ============================================================

# Global connection manager instance
_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get the singleton ConnectionManager instance."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager


async def shutdown_connection_manager() -> None:
    """Shutdown the connection manager on app shutdown."""
    global _connection_manager
    if _connection_manager is not None:
        await _connection_manager.shutdown()
        _connection_manager = None
