from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator
from urllib.parse import quote_plus

from psycopg import Connection, Error, OperationalError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.errors import DatabaseUnavailable


def database_url() -> str:
    if configured := os.getenv("DATABASE_URL"):
        return configured
    user = quote_plus(os.getenv("POSTGRES_USER", "hardtech_inventory"))
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", "hardtech_inventory"))
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    name = quote_plus(os.getenv("POSTGRES_DB", "hardtech_inventory"))
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


class Database:
    def __init__(self) -> None:
        self._pool: ConnectionPool | None = None

    def pool(self) -> ConnectionPool:
        if self._pool is None:
            self._pool = ConnectionPool(
                conninfo=database_url(),
                min_size=int(os.getenv("POSTGRES_POOL_MIN_SIZE", "1")),
                max_size=int(os.getenv("POSTGRES_POOL_MAX_SIZE", "10")),
                timeout=float(os.getenv("POSTGRES_POOL_TIMEOUT_SECONDS", "2")),
                kwargs={
                    "row_factory": dict_row,
                    "connect_timeout": int(os.getenv("POSTGRES_CONNECT_TIMEOUT_SECONDS", "2")),
                    "options": "-c statement_timeout=3000",
                },
                open=False,
            )
        return self._pool

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        try:
            pool = self.pool()
            if pool.closed:
                pool.open(wait=True)
            with pool.connection() as conn:
                yield conn
        except (OperationalError, Error) as exc:
            raise DatabaseUnavailable() from exc

    def close(self) -> None:
        if self._pool is not None and not self._pool.closed:
            self._pool.close()


database = Database()
