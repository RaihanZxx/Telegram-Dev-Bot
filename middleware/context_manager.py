"""Conversation context manager for maintaining chat history"""
from collections import defaultdict
from typing import Dict, List
from datetime import datetime, timedelta
from utils.logger import setup_logger

logger = setup_logger(__name__)

class ConversationContextManager:
    """Manages conversation context for groups"""
    
    def __init__(self, max_history: int = 20, ttl_minutes: int = 30):
        """
        Initialize context manager.
        
        Args:
            max_history: Maximum messages to keep in history
            ttl_minutes: Time to live for context in minutes
        """
        # group_id -> list of messages
        self._contexts: Dict[int, List[Dict]] = defaultdict(list)
        # group_id -> last_activity timestamp
        self._last_activity: Dict[int, datetime] = {}
        self.max_history = max_history
        self.ttl = timedelta(minutes=ttl_minutes)
    
    def add_message(self, group_id: int, role: str, content: str):
        """
        Add message to conversation history.
        
        Args:
            group_id: Group chat ID
            role: Message role (user/assistant)
            content: Message content
        """
        self._contexts[group_id].append({
            "role": role,
            "content": content
        })
        
        # Keep only recent messages
        if len(self._contexts[group_id]) > self.max_history:
            self._contexts[group_id] = self._contexts[group_id][-self.max_history:]
        
        self._last_activity[group_id] = datetime.now()
        logger.debug(f"Added message to group {group_id} context")
    
    def get_context(self, group_id: int) -> List[Dict]:
        """
        Get conversation context for a group.
        
        Args:
            group_id: Group chat ID
            
        Returns:
            List of messages in conversation
        """
        # Check if context expired
        if group_id in self._last_activity:
            if datetime.now() - self._last_activity[group_id] > self.ttl:
                logger.info(f"Context expired for group {group_id}, clearing")
                self.clear_context(group_id)
                return []
        
        return self._contexts.get(group_id, [])
    
    def clear_context(self, group_id: int):
        """
        Clear conversation context for a group.
        
        Args:
            group_id: Group chat ID
        """
        if group_id in self._contexts:
            del self._contexts[group_id]
        if group_id in self._last_activity:
            del self._last_activity[group_id]
        logger.info(f"Cleared context for group {group_id}")
    
    def cleanup_expired(self):
        """Clean up expired contexts"""
        now = datetime.now()
        expired_groups = [
            group_id for group_id, last_activity in self._last_activity.items()
            if now - last_activity > self.ttl
        ]
        
        for group_id in expired_groups:
            self.clear_context(group_id)
        
        if expired_groups:
            logger.info(f"Cleaned up {len(expired_groups)} expired contexts")

# Global context manager instance
context_manager = ConversationContextManager()
