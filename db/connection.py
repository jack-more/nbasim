"""SQLite database connection manager."""

import sqlite3
import logging
from contextlib import contextmanager

import pandas as pd

logger = logging.getLogger(__name__)


@contextmanager
def get_connection(db_path: str, foreign_keys: bool = True):
    """Context manager for SQLite connections."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_dataframe(df: pd.DataFrame, table_name: str, db_path: str,
                   if_exists: str = "append"):
    """Write a DataFrame to a SQLite table."""
    if df.empty:
        logger.warning(f"Empty DataFrame, skipping save to {table_name}")
        return
    with get_connection(db_path, foreign_keys=False) as conn:
        df.to_sql(table_name, conn, if_exists=if_exists, index=False)
    logger.info(f"Saved {len(df)} rows to {table_name}")


def read_query(query: str, db_path: str, params=None) -> pd.DataFrame:
    """Execute a SQL query and return results as DataFrame."""
    with get_connection(db_path) as conn:
        return pd.read_sql_query(query, conn, params=params)


def execute(query: str, db_path: str, params=None):
    """Execute a SQL statement (INSERT, UPDATE, DELETE, etc.)."""
    with get_connection(db_path, foreign_keys=False) as conn:
        conn.execute(query, params or [])


def table_row_count(table_name: str, db_path: str) -> int:
    """Get the row count of a table."""
    df = read_query(f"SELECT COUNT(*) as cnt FROM {table_name}", db_path)
    return int(df["cnt"].iloc[0])
