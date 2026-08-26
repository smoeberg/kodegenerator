"""
Resource Governor Service

Rate Limiter & Resource Governor for protecting external APIs (LLM tokens, API rate limits)
and system resources from swarm overload.

Features:
- Token Bucket rate limiter per capability/model provider
- Task Concurrency Limiter per file path to prevent merge conflicts
- Resource statistics tracking for tokens and wait times
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from pathlib import Path

if TYPE_CHECKING:
    from typing import AsyncIterator, Iterator


class ResourceType(str, Enum):
    """Types of resources that can be governed."""
    TOKENS = "tokens"
    REQUESTS = "requests"
    CONCURRENCY = "concurrency"


class RateLimitExceededError(Exception):
    """Raised when rate limit is exceeded."""
    pass


class ConcurrencyLimitExceededError(Exception):
    """Raised when concurrency limit is exceeded."""
    pass


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit."""
    capability: str
    resource_type: ResourceType = ResourceType.TOKENS
    max_tokens: int = 100000  # Max tokens per minute
    max_requests: int = 60  # Max requests per minute
    burst_size: int = 10  # Burst tolerance
    refill_rate: float = 1.0  # Tokens/second or requests/second
    
    def __post_init__(self) -> None:
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if self.burst_size < 0:
            raise ValueError("burst_size must be non-negative")
        if self.refill_rate <= 0:
            raise ValueError("refill_rate must be positive")


@dataclass
class ConcurrencyConfig:
    """Configuration for concurrency limiting."""
    max_concurrent_per_path: int = 5  # Max concurrent tasks per file path
    max_concurrent_global: int = 50  # Max concurrent tasks globally
    
    def __post_init__(self) -> None:
        if self.max_concurrent_per_path <= 0:
            raise ValueError("max_concurrent_per_path must be positive")
        if self.max_concurrent_global <= 0:
            raise ValueError("max_concurrent_global must be positive")


@dataclass
class ResourceStats:
    """Statistics for resource consumption."""
    capability: str
    total_tokens_consumed: int = 0
    total_requests: int = 0
    total_wait_time_seconds: float = 0.0
    rejected_count: int = 0
    average_wait_time: float = 0.0
    
    @property
    def average_tokens_per_request(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_tokens_consumed / self.total_requests


@dataclass
class BudgetAcquisition:
    """Result of a budget acquisition attempt."""
    granted: bool
    capability: str
    tokens_acquired: int = 0
    wait_time_seconds: float = 0.0
    remaining_budget: int = 0
    
    def __bool__(self) -> bool:
        return self.granted


class TokenBucket:
    """
    Token Bucket rate limiter implementation.
    
    Uses the token bucket algorithm for rate limiting with exact integer arithmetic.
    """
    
    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        burst_size: Optional[int] = None,
    ):
        """
        Initialize a token bucket.
        
        Args:
            capacity: Maximum number of tokens the bucket can hold
            refill_rate: Tokens added per second
            burst_size: Additional burst capacity (default: same as capacity)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        # burst_size defaults to capacity if not specified (None)
        # If explicitly set to 0, use 0
        if burst_size is None:
            self.burst_size = capacity
        else:
            self.burst_size = burst_size
        self.max_capacity = capacity + self.burst_size
        self._tokens = self.max_capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
    
    def refill(self) -> None:
        """Refill the bucket based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        
        # Calculate tokens to add and cap at max_capacity
        # Use floor to avoid adding partial tokens
        tokens_to_add = int(elapsed * self.refill_rate)
        self._tokens = min(self.max_capacity, self._tokens + tokens_to_add)
        self._last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from the bucket."""
        with self._lock:
            self.refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
    
    def consume_or_wait(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """Try to consume tokens, waiting if necessary."""
        start = time.monotonic()
        
        while True:
            with self._lock:
                self.refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                
                needed = tokens - self._tokens
                wait_time = needed / self.refill_rate if self.refill_rate > 0 else float('inf')
            
            elapsed = time.monotonic() - start
            if timeout is not None and elapsed + wait_time > timeout:
                return False
            
            time.sleep(min(wait_time, 0.1))
    
    def available_tokens(self) -> int:
        """Get the current number of available tokens (integer)."""
        with self._lock:
            self.refill()
            return self._tokens
    
    def reset(self) -> None:
        """Reset the bucket to full capacity."""
        with self._lock:
            self._tokens = self.max_capacity
            self._last_refill = time.monotonic()


class AsyncTokenBucket:
    """Async version of TokenBucket for use with asyncio."""
    
    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        burst_size: Optional[int] = None,
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        # burst_size defaults to capacity if not specified (None)
        # If explicitly set to 0, use 0
        if burst_size is None:
            self.burst_size = capacity
        else:
            self.burst_size = burst_size
        self.max_capacity = capacity + self.burst_size
        self._tokens = self.max_capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def refill(self) -> None:
        """Refill the bucket based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        
        tokens_to_add = int(elapsed * self.refill_rate)
        self._tokens = min(self.max_capacity, self._tokens + tokens_to_add)
        self._last_refill = now
    
    async def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from the bucket."""
        async with self._lock:
            await self.refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
    
    async def consume_or_wait(
        self,
        tokens: int = 1,
        timeout: Optional[float] = None,
    ) -> bool:
        """Try to consume tokens, waiting if necessary."""
        start = time.monotonic()
        
        while True:
            async with self._lock:
                await self.refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
                
                needed = tokens - self._tokens
                wait_time = needed / self.refill_rate if self.refill_rate > 0 else float('inf')
            
            elapsed = time.monotonic() - start
            if timeout is not None and elapsed + wait_time > timeout:
                return False
            
            await asyncio.sleep(min(wait_time, 0.1))
    
    def available_tokens(self) -> int:
        """Get the current number of available tokens (integer)."""
        return self._tokens
    
    def reset(self) -> None:
        """Reset the bucket to full capacity."""
        self._tokens = self.max_capacity
        self._last_refill = time.monotonic()


class ResourceGovernor:
    """
    Resource Governor for protecting external APIs and system resources.
    
    Features:
    - Token Bucket rate limiter per capability/model provider
    - Task Concurrency Limiter per file path
    - Resource statistics tracking
    
    Usage:
        governor = ResourceGovernor()
        
        # Acquire budget for a capability
        if governor.acquire_budget("llm:gpt-4", estimated_tokens=1000):
            # Proceed with API call
            pass
        else:
            # Rate limit exceeded
            pass
        
        # Or use context manager for automatic release
        async with governor.acquire_concurrency("path/to/file.py"):
            # Process file
            pass
    """
    
    # Default rate limits per capability
    DEFAULT_RATE_LIMITS: Dict[str, RateLimitConfig] = {
        "llm:gpt-4": RateLimitConfig(
            capability="llm:gpt-4",
            resource_type=ResourceType.TOKENS,
            max_tokens=100000,  # 100k tokens/minute
            max_requests=60,    # 60 requests/minute
            burst_size=10000,   # Burst of 10k tokens
            refill_rate=100000.0 / 60.0,  # Refill rate
        ),
        "llm:gpt-3.5": RateLimitConfig(
            capability="llm:gpt-3.5",
            resource_type=ResourceType.TOKENS,
            max_tokens=200000,
            max_requests=120,
            burst_size=20000,
            refill_rate=200000.0 / 60.0,
        ),
        "llm:claude": RateLimitConfig(
            capability="llm:claude",
            resource_type=ResourceType.TOKENS,
            max_tokens=150000,
            max_requests=90,
            burst_size=15000,
            refill_rate=150000.0 / 60.0,
        ),
        "api:github": RateLimitConfig(
            capability="api:github",
            resource_type=ResourceType.REQUESTS,
            max_tokens=5000,  # 5000 requests/minute
            max_requests=5000,
            burst_size=100,
            refill_rate=5000.0 / 60.0,
        ),
        "api:gitlab": RateLimitConfig(
            capability="api:gitlab",
            resource_type=ResourceType.REQUESTS,
            max_tokens=6000,
            max_requests=6000,
            burst_size=100,
            refill_rate=6000.0 / 60.0,
        ),
        "default": RateLimitConfig(
            capability="default",
            resource_type=ResourceType.REQUESTS,
            max_tokens=60,
            max_requests=60,
            burst_size=10,
            refill_rate=1.0,
        ),
    }
    
    def __init__(
        self,
        *,
        rate_limits: Optional[Dict[str, RateLimitConfig]] = None,
        concurrency_config: Optional[ConcurrencyConfig] = None,
        track_stats: bool = True,
    ):
        """
        Initialize the Resource Governor.
        
        Args:
            rate_limits: Custom rate limits per capability (overrides defaults)
            concurrency_config: Configuration for concurrency limiting
            track_stats: Whether to track resource statistics
        """
        self._rate_limits = rate_limits or {}
        self._concurrency_config = concurrency_config or ConcurrencyConfig()
        self._track_stats = track_stats
        
        # Token buckets per capability
        self._token_buckets: Dict[str, TokenBucket] = {}
        self._request_buckets: Dict[str, TokenBucket] = {}
        
        # Concurrency tracking
        self._path_locks: Dict[str, asyncio.Semaphore] = {}
        self._path_counts: Dict[str, int] = defaultdict(int)
        self._global_semaphore = asyncio.Semaphore(self._concurrency_config.max_concurrent_global)
        
        # Statistics
        self._stats: Dict[str, ResourceStats] = defaultdict(
            lambda: ResourceStats(capability="")
        )
        self._stats_lock = threading.Lock()
        
        # Initialize buckets for default rate limits
        for capability, config in self.DEFAULT_RATE_LIMITS.items():
            self._initialize_bucket(capability, config)
    
    def _initialize_bucket(self, capability: str, config: RateLimitConfig) -> None:
        """Initialize token buckets for a capability."""
        # Always create token bucket (for token tracking)
        self._token_buckets[capability] = TokenBucket(
            capacity=config.max_tokens,
            refill_rate=config.refill_rate,
            burst_size=config.burst_size,
        )
        
        # Always create request bucket (for request rate limiting)
        self._request_buckets[capability] = TokenBucket(
            capacity=config.max_requests,
            refill_rate=config.refill_rate,
            burst_size=config.burst_size,
        )
    
    def _get_config(self, capability: str) -> RateLimitConfig:
        """Get the rate limit config for a capability."""
        if capability in self._rate_limits:
            return self._rate_limits[capability]
        if capability in self.DEFAULT_RATE_LIMITS:
            return self.DEFAULT_RATE_LIMITS[capability]
        return self.DEFAULT_RATE_LIMITS["default"]
    
    def _ensure_bucket(self, capability: str) -> None:
        """Ensure token buckets exist for a capability."""
        if capability not in self._token_buckets:
            config = self._get_config(capability)
            self._initialize_bucket(capability, config)
    
    def acquire_budget(
        self,
        capability: str,
        estimated_tokens: int = 0,
        wait: bool = False,
        timeout: Optional[float] = None,
    ) -> BudgetAcquisition:
        """
        Acquire budget for a capability.
        
        This method checks if there is enough budget (tokens and request quota)
        for the given capability. If wait is True, it will block until budget
        is available or timeout is reached.
        
        Args:
            capability: The capability to acquire budget for
            estimated_tokens: Estimated number of tokens to be consumed
            wait: Whether to wait if budget is not available
            timeout: Maximum time to wait (None = wait forever)
            
        Returns:
            BudgetAcquisition with granted status and details
        """
        start_time = time.monotonic()
        self._ensure_bucket(capability)
        
        config = self._get_config(capability)
        
        # Try to acquire request quota
        request_bucket = self._request_buckets[capability]
        
        if wait:
            request_granted = request_bucket.consume_or_wait(timeout=timeout)
        else:
            request_granted = request_bucket.consume()
        
        if not request_granted:
            self._record_rejection(capability)
            return BudgetAcquisition(
                granted=False,
                capability=capability,
                wait_time_seconds=time.monotonic() - start_time,
            )
        
        # Try to acquire token budget
        token_bucket = self._token_buckets[capability]
        
        if wait:
            token_granted = token_bucket.consume_or_wait(estimated_tokens, timeout=timeout)
        else:
            token_granted = token_bucket.consume(estimated_tokens)
        
        if not token_granted:
            # Release the request quota we acquired
            request_bucket.reset()
            self._record_rejection(capability)
            return BudgetAcquisition(
                granted=False,
                capability=capability,
                wait_time_seconds=time.monotonic() - start_time,
            )
        
        # Budget acquired successfully
        wait_time = time.monotonic() - start_time
        remaining_tokens = int(token_bucket.available_tokens())
        
        self._record_acquisition(capability, estimated_tokens, wait_time)
        
        return BudgetAcquisition(
            granted=True,
            capability=capability,
            tokens_acquired=estimated_tokens,
            wait_time_seconds=wait_time,
            remaining_budget=remaining_tokens,
        )
    
    def release_budget(
        self,
        capability: str,
        tokens_consumed: int = 0,
    ) -> None:
        """
        Release budget that was acquired but not fully used.
        
        This can be called to return unused tokens to the budget.
        
        Args:
            capability: The capability to release budget for
            tokens_consumed: Actual number of tokens consumed (not released)
        """
        if capability not in self._token_buckets:
            return
        
        # For now, we don't track per-acquisition releases
        # The bucket will naturally refill over time
        # In a more sophisticated implementation, we could track individual acquisitions
        pass
    
    async def acquire_concurrency(
        self,
        file_path: str,
        timeout: Optional[float] = None,
    ) -> "AsyncConcurrencyGuard":
        """
        Acquire concurrency slot for a file path.
        
        This limits the number of concurrent tasks working on the same file
        to prevent merge conflicts.
        
        Args:
            file_path: The file path to acquire concurrency for
            timeout: Maximum time to wait for a slot
            
        Returns:
            AsyncConcurrencyGuard context manager
        """
        return AsyncConcurrencyGuard(self, file_path, timeout)
    
    def acquire_concurrency_sync(
        self,
        file_path: str,
        timeout: Optional[float] = None,
    ) -> "ConcurrencyGuard":
        """
        Synchronous version of acquire_concurrency.
        
        Args:
            file_path: The file path to acquire concurrency for
            timeout: Maximum time to wait for a slot
            
        Returns:
            ConcurrencyGuard context manager
        """
        return ConcurrencyGuard(self, file_path, timeout)
    
    def get_stats(self, capability: Optional[str] = None) -> Dict[str, ResourceStats]:
        """
        Get resource statistics.
        
        Args:
            capability: Optional capability filter
            
        Returns:
            Dictionary of ResourceStats per capability
        """
        if capability:
            return {capability: self._stats.get(capability, ResourceStats(capability=capability))}
        return dict(self._stats)
    
    def reset(self, capability: Optional[str] = None) -> None:
        """
        Reset rate limits.
        
        Args:
            capability: Optional capability to reset (resets all if None)
        """
        if capability:
            if capability in self._token_buckets:
                self._token_buckets[capability].reset()
            if capability in self._request_buckets:
                self._request_buckets[capability].reset()
        else:
            for bucket in self._token_buckets.values():
                bucket.reset()
            for bucket in self._request_buckets.values():
                bucket.reset()
    
    def _record_acquisition(
        self,
        capability: str,
        tokens: int,
        wait_time: float,
    ) -> None:
        """Record a budget acquisition in statistics."""
        if not self._track_stats:
            return
        
        with self._stats_lock:
            if capability not in self._stats:
                self._stats[capability] = ResourceStats(capability=capability)
            
            stats = self._stats[capability]
            stats.total_tokens_consumed += tokens
            stats.total_requests += 1
            stats.total_wait_time_seconds += wait_time
            
            # Recalculate average
            if stats.total_requests > 0:
                stats.average_wait_time = stats.total_wait_time_seconds / stats.total_requests
    
    def _record_rejection(self, capability: str) -> None:
        """Record a rejection in statistics."""
        if not self._track_stats:
            return
        
        with self._stats_lock:
            if capability not in self._stats:
                self._stats[capability] = ResourceStats(capability=capability)
            
            self._stats[capability].rejected_count += 1


class ConcurrencyGuard:
    """
    Synchronous context manager for concurrency limiting.
    """
    
    def __init__(
        self,
        governor: ResourceGovernor,
        file_path: str,
        timeout: Optional[float] = None,
    ):
        self._governor = governor
        self._file_path = file_path
        self._timeout = timeout
        self._acquired = False
        self._lock = threading.Lock()
    
    def __enter__(self) -> "ConcurrencyGuard":
        start = time.monotonic()
        
        while True:
            with self._lock:
                # Check global limit
                if len(self._governor._path_counts) >= self._governor._concurrency_config.max_concurrent_global:
                    if self._timeout and (time.monotonic() - start) > self._timeout:
                        raise ConcurrencyLimitExceededError(
                            f"Global concurrency limit exceeded for {self._file_path}"
                        )
                    time.sleep(0.01)
                    continue
                
                # Check per-path limit
                current = self._governor._path_counts[self._file_path]
                if current >= self._governor._concurrency_config.max_concurrent_per_path:
                    if self._timeout and (time.monotonic() - start) > self._timeout:
                        raise ConcurrencyLimitExceededError(
                            f"Concurrency limit exceeded for {self._file_path}"
                        )
                    time.sleep(0.01)
                    continue
                
                # Acquire
                self._governor._path_counts[self._file_path] += 1
                self._acquired = True
                return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._acquired:
            self._governor._path_counts[self._file_path] -= 1
            if self._governor._path_counts[self._file_path] <= 0:
                del self._governor._path_counts[self._file_path]


class AsyncConcurrencyGuard:
    """
    Asynchronous context manager for concurrency limiting.
    """
    
    def __init__(
        self,
        governor: ResourceGovernor,
        file_path: str,
        timeout: Optional[float] = None,
    ):
        self._governor = governor
        self._file_path = file_path
        self._timeout = timeout
        self._acquired_global = False
        self._acquired_path = False
    
    async def __aenter__(self) -> "AsyncConcurrencyGuard":
        start = time.monotonic()
        
        # Ensure per-path semaphore exists
        if self._file_path not in self._governor._path_locks:
            self._governor._path_locks[self._file_path] = asyncio.Semaphore(
                self._governor._concurrency_config.max_concurrent_per_path
            )
        
        # Try to acquire per-path semaphore first (most restrictive)
        # Use a very short timeout to check immediately
        try:
            await asyncio.wait_for(
                self._governor._path_locks[self._file_path].acquire(),
                timeout=0.0001,
            )
            self._acquired_path = True
        except asyncio.TimeoutError:
            # Per-path limit reached, fail immediately
            if self._timeout and (time.monotonic() - start) >= self._timeout:
                raise ConcurrencyLimitExceededError(
                    f"Concurrency limit timeout for {self._file_path}"
                )
            raise ConcurrencyLimitExceededError(
                f"Concurrency limit exceeded for {self._file_path}"
            )
        
        # Now acquire global semaphore
        while True:
            elapsed = time.monotonic() - start
            remaining_timeout = self._timeout - elapsed if self._timeout else None
            
            try:
                await asyncio.wait_for(
                    self._governor._global_semaphore.acquire(),
                    timeout=min(0.001, remaining_timeout) if remaining_timeout and remaining_timeout > 0 else 0.001,
                )
                self._acquired_global = True
                break
            except asyncio.TimeoutError:
                # Release per-path semaphore if we acquired it
                if self._acquired_path:
                    self._governor._path_locks[self._file_path].release()
                    self._acquired_path = False
                if self._timeout and elapsed >= self._timeout:
                    raise ConcurrencyLimitExceededError(
                        f"Global concurrency limit timeout for {self._file_path}"
                    )
                # Retry
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._acquired_path:
            self._governor._path_locks[self._file_path].release()
        if self._acquired_global:
            self._governor._global_semaphore.release()


# Global governor instance
_governor: Optional[ResourceGovernor] = None


def get_resource_governor(**kwargs) -> ResourceGovernor:
    """Get or create the global ResourceGovernor instance."""
    global _governor
    if _governor is None:
        _governor = ResourceGovernor(**kwargs)
    return _governor


def acquire_budget(
    capability: str,
    estimated_tokens: int = 0,
    wait: bool = False,
    timeout: Optional[float] = None,
) -> BudgetAcquisition:
    """Convenience function to acquire budget."""
    governor = get_resource_governor()
    return governor.acquire_budget(
        capability=capability,
        estimated_tokens=estimated_tokens,
        wait=wait,
        timeout=timeout,
    )
