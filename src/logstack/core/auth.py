"""
Authentication and rate limiting middleware.
"""

import asyncio
import time
from typing import Dict, Optional

import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..config import get_settings
from .exceptions import AuthenticationError, RateLimitError

logger = structlog.get_logger(__name__)
security = HTTPBearer()


class TokenBucket:
    """
    Token bucket rate limiter implementation.
    
    """
    
    def __init__(self, capacity: int, refill_rate: int) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        self.lock = asyncio.Lock()
    
    async def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from bucket.
        
        Returns True if tokens available, False otherwise.
        """
        async with self.lock:
            now = time.time()
            time_passed = now - self.last_refill
            
            # Add tokens based on time passed
            tokens_to_add = int(time_passed * self.refill_rate)
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill = now
            
            # Try to consume requested tokens
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            return False
    
    def get_retry_after(self) -> int:
        """Get suggested retry-after time in seconds."""
        return max(1, int((1 - self.tokens) / self.refill_rate))


class RateLimiter:
    """
    Per-token rate limiter using token buckets.
    """
    
    def __init__(self, rps: int, burst: int) -> None:
        self.rps = rps
        self.burst = burst
        self.buckets: Dict[str, TokenBucket] = {}
    
    async def check_rate_limit(self, token: str) -> None:
        """
        Check rate limit for token.
        
        Raises RateLimitError if limit exceeded.
        """
        # Get or create bucket for token
        if token not in self.buckets:
            logger.info(
                "Creating new rate limit bucket",
                token=token[:8] + "...",
                capacity=self.burst,
                refill_rate=self.rps
            )
            self.buckets[token] = TokenBucket(
                capacity=self.burst,
                refill_rate=self.rps,
            )
        
        bucket = self.buckets[token]
        
        if not await bucket.consume():
            retry_after = bucket.get_retry_after()
            logger.warning(
                "Rate limit exceeded",
                token=token[:8] + "...",
                retry_after=retry_after,
                remaining_tokens=bucket.tokens,
                bucket_capacity=bucket.capacity
            )
            raise RateLimitError(
                message=f"Rate limit exceeded for token",
                retry_after=retry_after,
            )
        else:
            # Log successful rate limit check (debug level)
            logger.debug(
                "Rate limit check passed",
                token=token[:8] + "...",
                remaining_tokens=bucket.tokens,
                bucket_capacity=bucket.capacity
            )


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter."""
    global _rate_limiter
    
    if _rate_limiter is None:
        settings = get_settings()
        _rate_limiter = RateLimiter(
            rps=settings.security.rate_limit_rps,
            burst=settings.security.rate_limit_burst,
        )
    
    return _rate_limiter


async def authenticate_token(token: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    Authenticate bearer token against configured API keys.
    
    Validates the token exists in config and is active.
    """
    if not token or not token.credentials:
        raise AuthenticationError("Missing authentication token")
    
    token_value = token.credentials.strip()
    
    # Get valid API keys from config
    settings = get_settings()
    valid_keys = settings.security.api_keys
    
    # Check if token exists and is active
    if token_value not in valid_keys:
        logger.warning(
            "Authentication failed: unknown token", 
            token=token_value[:8] + "..." if len(token_value) >= 8 else "invalid"
        )
        raise AuthenticationError("Invalid authentication token")
    
    key_info = valid_keys[token_value]
    if not key_info.get("active", False):
        logger.warning(
            "Authentication failed: inactive token",
            token=token_value[:8] + "...",
            key_name=key_info.get("name", "unknown")
        )
        raise AuthenticationError("Authentication token is inactive")
    
    logger.debug(
        "Token authenticated successfully",
        token=token_value[:8] + "...",
        key_name=key_info.get("name", "unknown")
    )
    
    return token_value


async def check_rate_limit(token: str) -> None:
    """
    Check rate limit for authenticated token.
    
    Should be called after authentication in the request pipeline.
    """
    rate_limiter = get_rate_limiter()
    await rate_limiter.check_rate_limit(token)
