import logging
import os
import time
from collections.abc import Callable


def env_flag(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def run_job(job_name: str, extract: Callable[[], None]) -> None:
    run_once = env_flag("RUN_ONCE", True)
    interval = max(1, int(os.getenv("SNAPSHOT_INTERVAL_SECONDS", "300")))
    log = logging.getLogger(job_name)

    while True:
        try:
            extract()
        except Exception:
            log.exception("%s failed", job_name)
            if run_once:
                raise

        if run_once:
            return

        log.info("%s completed; next snapshot in %d seconds", job_name, interval)
        time.sleep(interval)
