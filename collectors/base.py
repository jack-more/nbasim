"""Base collector with rate limiting, retry logic, and DataFrame conversion."""

import time
import logging

import pandas as pd

from utils.rate_limiter import RateLimiter
from db.connection import save_dataframe

logger = logging.getLogger(__name__)


class BaseCollector:
    """Base class for all data collectors."""

    def __init__(self, db_path: str, delay: float = 2.0, max_retries: int = 3):
        self.db_path = db_path
        self.rate_limiter = RateLimiter(min_delay=delay)
        self.max_retries = max_retries

    def _call_endpoint(self, endpoint_class, **params) -> list[pd.DataFrame]:
        """
        Rate-limited wrapper around any nba_api endpoint class.
        Returns list of DataFrames from get_data_frames().
        """
        for attempt in range(self.max_retries):
            self.rate_limiter.wait()
            try:
                endpoint = endpoint_class(**params)
                dfs = endpoint.get_data_frames()
                return dfs
            except Exception as e:
                error_msg = str(e)
                if attempt < self.max_retries - 1:
                    logger.warning(
                        f"Attempt {attempt + 1}/{self.max_retries} failed for "
                        f"{endpoint_class.__name__}: {error_msg}"
                    )
                    self.rate_limiter.backoff(attempt)
                else:
                    logger.error(
                        f"All {self.max_retries} attempts failed for "
                        f"{endpoint_class.__name__}: {error_msg}"
                    )
                    raise

    def _save(self, df: pd.DataFrame, table_name: str, if_exists: str = "append"):
        """Save DataFrame to database."""
        save_dataframe(df, table_name, self.db_path, if_exists=if_exists)

    def collect_for_season(self, season: str):
        """Override in subclasses."""
        raise NotImplementedError
