"""Rate limiting to prevent spam"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Tuple
from config.settings import RATE_LIMIT_MESSAGES, RATE_LIMIT_WINDOW
from utils.logger import setup_logger

logger = setup_logger(__name__)

class RateLimiter:
    """Simple rate limiter using sliding window"""
    
    def __init__(self):
        # user_id -> list of timestamps
        self._requests: Dict[int, list] = defaultdict(list)
    
    def is_allowed(self, user_id: int) -> Tuple[bool, int]:
        """
        Check if user is allowed to make a request.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Tuple of (is_allowed, remaining_seconds_if_blocked)
        """
        now = datetime.now()
        window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
        
        # Clean old requests
        self._requests[user_id] = [
            ts for ts in self._requests[user_id]
            if ts > window_start
        ]
        
        # Check if limit exceeded
        if len(self._requests[user_id]) >= RATE_LIMIT_MESSAGES:
            oldest_request = min(self._requests[user_id])
            wait_time = int((oldest_request + timedelta(seconds=RATE_LIMIT_WINDOW) - now).total_seconds())
            logger.warning(f"Rate limit exceeded for user {user_id}")
            return False, max(0, wait_time)
        
        # Add current request
        self._requests[user_id].append(now)
        return True, 0
    
    def reset_user(self, user_id: int):
        """Reset rate limit for a specific user"""
        if user_id in self._requests:
            del self._requests[user_id]
            logger.info(f"Rate limit reset for user {user_id}")

# Global rate limiter instance
rate_limiter = RateLimiter()
