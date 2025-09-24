"""
Tests for RateLimiter class that manages per-token buckets.

Tests the token bucket management and per-token isolation.
"""

import asyncio
import pytest

from src.logstack.core.auth import RateLimiter
from src.logstack.core.exceptions import RateLimitError


class TestRateLimiter:
    """Test the RateLimiter class that manages per-token buckets."""

    @pytest.mark.asyncio
    async def test_per_token_bucket_creation(self) -> None:
        """Test bucket creation for each unique token."""

        rate_limiter = RateLimiter(rps=1, burst=1)
        await rate_limiter.check_rate_limit("test_token")
        assert rate_limiter.buckets["test_token"] is not None
        assert rate_limiter.buckets["test_token"].capacity == 1
        assert rate_limiter.buckets["test_token"].refill_rate == 1

    @pytest.mark.asyncio
    async def test_per_token_isolation(self) -> None:
        """Test that rate limiting is isolated per token."""

        rate_limiter = RateLimiter(rps=1, burst=1)
        await rate_limiter.check_rate_limit("test_token1")
        await rate_limiter.check_rate_limit("test_token2")
        assert rate_limiter.buckets["test_token2"] is not None
        assert rate_limiter.buckets["test_token2"].capacity == 1
        assert rate_limiter.buckets["test_token2"].refill_rate == 1
        with pytest.raises(RateLimitError):
            await rate_limiter.check_rate_limit("test_token1")

    @pytest.mark.asyncio
    async def test_rate_limit_exception_details(self) -> None:
        """Test RateLimitError contains proper retry_after."""

        rate_limiter = RateLimiter(rps=1, burst=1)
        await rate_limiter.check_rate_limit("test_token")
        with pytest.raises(RateLimitError):
            await rate_limiter.check_rate_limit("test_token")
        assert rate_limiter.buckets["test_token"].get_retry_after() is not None
        assert rate_limiter.buckets["test_token"].get_retry_after() == 1

    @pytest.mark.asyncio
    async def test_bucket_reuse_for_same_token(self) -> None:
        """Test same token reuses existing bucket."""

        rate_limiter = RateLimiter(rps=1, burst=1)
        await rate_limiter.check_rate_limit("test_token")
        assert rate_limiter.buckets["test_token"] is not None
        assert rate_limiter.buckets["test_token"].capacity == 1
        assert rate_limiter.buckets["test_token"].refill_rate == 1
        with pytest.raises(RateLimitError):
            await rate_limiter.check_rate_limit("test_token")
        assert rate_limiter.buckets["test_token"].tokens == 0

    @pytest.mark.asyncio
    async def test_multiple_tokens_concurrent(self) -> None:
        """Test multiple tokens can be processed concurrently."""

        rate_limiter = RateLimiter(rps=1, burst=1)
        tasks = [
            rate_limiter.check_rate_limit("test_token1"),
            rate_limiter.check_rate_limit("test_token2"),
        ]
        await asyncio.gather(*tasks)
        assert rate_limiter.buckets["test_token1"] is not None
        assert rate_limiter.buckets["test_token1"].tokens == 0
        assert rate_limiter.buckets["test_token2"] is not None
        assert rate_limiter.buckets["test_token2"].tokens == 0
