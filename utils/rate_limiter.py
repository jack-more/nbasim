import time
import logging

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token-bucket rate limiter for nba_api calls."""

    def __init__(self, min_delay: float = 2.0):
        self.min_delay = min_delay
        self.last_call_time = 0.0

    def wait(self):
        """Block until at least min_delay seconds since last call."""
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_delay:
            sleep_time = self.min_delay - elapsed
            logger.debug(f"Rate limiter sleeping {sleep_time:.1f}s")
            time.sleep(sleep_time)
        self.last_call_time = time.time()

    def backoff(self, attempt: int):
        """Exponential backoff: sleep for min_delay * 2^attempt."""
        sleep_time = self.min_delay * (2 ** attempt)
        logger.warning(f"Backoff attempt {attempt}: sleeping {sleep_time:.1f}s")
        time.sleep(sleep_time)
