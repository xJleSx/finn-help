import threading

from src.portfolio.allocator.engine import PortfolioAllocator

allocator = PortfolioAllocator()
_allocator_lock = threading.Lock()

# NOTE: Module-level allocator is not thread-safe.
# Use _allocator_lock when accessing from multiple threads.

__all__ = ["PortfolioAllocator", "allocator", "_allocator_lock"]
