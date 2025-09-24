"""
Tests for TokenBucket rate limiter implementation.

Tests the core token bucket algorithm for rate limiting.
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from src.logstack.core.auth import TokenBucket


class TestTokenBucket:
    """Test the TokenBucket rate limiter implementation."""
    
    @pytest.mark.asyncio
    async def test_token_consumption_success(self) -> None:
        """Test successful token consumption from bucket."""

        bucket = TokenBucket(capacity=5, refill_rate=2)
        assert await bucket.consume(3) is True
        assert bucket.tokens == 2
        assert await bucket.consume(2) is True
        assert bucket.tokens == 0
    
    @pytest.mark.asyncio
    async def test_token_consumption_failure(self) -> None:
        """Test token consumption failure when bucket empty."""

        bucket = TokenBucket(capacity=2, refill_rate=2)
        assert await bucket.consume(2) is True
        assert await bucket.consume(1) is False
    
    @pytest.mark.asyncio
    async def test_token_refill_calculation(self) -> None:
        """Test token refill calculation based on time."""

        bucket = TokenBucket(capacity=5, refill_rate=5)
        await bucket.consume(5)
        assert bucket.tokens == 0
        with patch("time.time") as mock_time:
            mock_time.return_value = bucket.last_refill + 2
            assert await bucket.consume(5) is True
            assert bucket.tokens == 0
    
    @pytest.mark.asyncio
    async def test_token_refill_cap_at_capacity(self) -> None:
        """Test token refill doesn't exceed bucket capacity."""

        # - Create bucket capacity=10, rate=5
        bucket = TokenBucket(capacity=10, refill_rate=5)
        # - Start with 8 tokens
        await bucket.consume(8)
        assert bucket.tokens == 2
        # - Simulate long time passing (should refill many tokens)
        with patch("time.time") as mock_time:
            mock_time.return_value = bucket.last_refill + 10
            assert await bucket.consume(10) is True
            mock_time.return_value = bucket.last_refill + 15
            await bucket.consume(0)
            assert bucket.tokens == 10

    @pytest.mark.asyncio
    async def test_retry_after_calculation(self) -> None:
        """Test retry-after time calculation."""

        # - Create bucket with known rate
        bucket = TokenBucket(capacity=5, refill_rate=5)
        # - Consume all tokens
        await bucket.consume(5)
        assert bucket.tokens == 0
        expected_retry_time = max(1, int((1 - bucket.tokens) / bucket.refill_rate))
        assert bucket.get_retry_after() == expected_retry_time
    
    @pytest.mark.asyncio
    async def test_concurrent_consumption(self) -> None:
        """Test thread safety of concurrent token consumption."""

        bucket = TokenBucket(capacity=3, refill_rate=1)
        tasks = [bucket.consume() for _ in range(5)]
        results = await asyncio.gather(*tasks)
        assert bucket.tokens == 0
        assert results.count(True) == 3
        assert results.count(False) == 2
