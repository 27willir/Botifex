"""Scraper metrics tracking and aggregation utilities."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Deque, Dict, Iterable, List, Optional

from utils import logger


DEFAULT_SCRAPERS: Iterable[str] = (
    "craigslist",
    "ebay",
    "facebook",
    "ksl",
    "mercari",
    "poshmark",
)

_MAX_HISTORY = 200
_metrics_data: Dict[str, Deque[Dict[str, Any]]] = {}
_metrics_lock = Lock()


def _now() -> datetime:
    return datetime.utcnow()


def _ensure_scraper_queue(scraper_name: str) -> Deque[Dict[str, Any]]:
    if scraper_name not in _metrics_data:
        _metrics_data[scraper_name] = deque(maxlen=_MAX_HISTORY)
    return _metrics_data[scraper_name]


def record_scraper_run(
    scraper_name: str,
    *,
    start_time: datetime,
    end_time: datetime,
    duration: float,
    success: bool,
    listings_found: int,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a completed scraper run in the metrics store."""

    run = {
        "start_time": start_time,
        "end_time": end_time,
        "duration": duration,
        "success": bool(success),
        "listings_found": int(listings_found or 0),
        "error": error,
        "metadata": metadata or {},
    }

    with _metrics_lock:
        queue = _ensure_scraper_queue(scraper_name)
        queue.append(run)


def reset_metrics(scraper_name: Optional[str] = None) -> None:
    """Clear stored metrics for a specific scraper or all scrapers."""

    with _metrics_lock:
        if scraper_name:
            _metrics_data.pop(scraper_name, None)
        else:
            _metrics_data.clear()


def _filter_runs(runs: Iterable[Dict[str, Any]], hours: Optional[int]) -> List[Dict[str, Any]]:
    if hours is None:
        return list(runs)

    cutoff = _now() - timedelta(hours=hours)
    return [run for run in runs if run["end_time"] >= cutoff]


def _serialize_run(run: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": run["end_time"].isoformat(),
        "start_time": run["start_time"].isoformat(),
        "duration": run["duration"],
        "success": run["success"],
        "listings_found": run["listings_found"],
        "error": run["error"],
        "metadata": run.get("metadata", {}),
    }


def _summarize_runs(scraper_name: str, runs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    runs_list = list(runs)
    total_runs = len(runs_list)

    if total_runs == 0:
        return {
            "scraper": scraper_name,
            "total_runs": 0,
            "successful_runs": 0,
            "failed_runs": 0,
            "success_rate": 0.0,
            "total_listings": 0,
            "avg_listings_per_run": 0.0,
            "avg_duration": 0.0,
            "last_run": None,
        }

    successful_runs = sum(1 for run in runs_list if run["success"])
    failed_runs = total_runs - successful_runs
    total_listings = sum(run["listings_found"] for run in runs_list)
    total_duration = sum(run["duration"] for run in runs_list)

    success_rate = (successful_runs / total_runs) * 100 if total_runs else 0.0
    avg_listings = total_listings / total_runs if total_runs else 0.0
    avg_duration = total_duration / total_runs if total_runs else 0.0

    last_run = _serialize_run(runs_list[-1]) if runs_list else None

    return {
        "scraper": scraper_name,
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "failed_runs": failed_runs,
        "success_rate": round(success_rate, 1),
        "total_listings": total_listings,
        "avg_listings_per_run": round(avg_listings, 2),
        "avg_duration": round(avg_duration, 2),
        "last_run": last_run,
    }


def get_metrics_summary(
    scraper_name: Optional[str] = None,
    *,
    hours: Optional[int] = 24,
) -> Dict[str, Any]:
    """Return aggregated metrics for one or all scrapers within the time window."""

    with _metrics_lock:
        if scraper_name is None:
            known_scrapers = set(DEFAULT_SCRAPERS) | set(_metrics_data.keys())
            runs_map = {
                name: list(_filter_runs(_metrics_data.get(name, []), hours))
                for name in known_scrapers
            }
        else:
            runs_map = {
                scraper_name: list(
                    _filter_runs(_metrics_data.get(scraper_name, []), hours)
                )
            }

    if scraper_name is None:
        return {
            name: _summarize_runs(name, runs_map[name])
            for name in sorted(runs_map.keys())
        }

    return _summarize_runs(scraper_name, runs_map.get(scraper_name, []))


def get_recent_runs(
    scraper_name: str,
    *,
    limit: int = 20,
    hours: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return the most recent scraper runs up to the requested limit."""

    with _metrics_lock:
        runs = list(_metrics_data.get(scraper_name, []))

    filtered = _filter_runs(runs, hours)
    recent = filtered[-limit:]
    return [_serialize_run(run) for run in reversed(recent)]


def get_performance_status(scraper_name: str, *, hours: Optional[int] = 24) -> str:
    """Return a simple health status string for the scraper."""

    summary = get_metrics_summary(scraper_name, hours=hours)

    if summary["total_runs"] == 0:
        return "unknown"

    rate = summary["success_rate"]

    if rate >= 95:
        return "excellent"
    if rate >= 80:
        return "good"
    if rate >= 50:
        return "degraded"
    return "poor"


class ScraperMetrics:
    """Context manager for tracking individual scraper runs."""

    def __init__(self, scraper_name: str):
        self.scraper_name = scraper_name
        self.success: Optional[bool] = None
        self.error: Optional[str] = None
        self.listings_found: int = 0
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.metadata: Dict[str, Any] = {}

    def __enter__(self) -> "ScraperMetrics":
        self.start_time = _now()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.end_time = _now()

        if exc_val and not self.error:
            self.error = str(exc_val)

        success_flag = self.success
        if success_flag is None:
            success_flag = exc_type is None and self.error is None

        if exc_type or self.error:
            success_flag = False

        duration = 0.0
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()

        message_base = (
            f"[{self.scraper_name}] duration={duration:.2f}s, listings={self.listings_found}"
        )

        if not success_flag:
            logger.warning(
                f"{message_base}, status=failed, error={self.error or exc_val}"
            )
        else:
            logger.debug(f"{message_base}, status=success")

        try:
            record_scraper_run(
                self.scraper_name,
                start_time=self.start_time or _now(),
                end_time=self.end_time or _now(),
                duration=duration,
                success=success_flag,
                listings_found=self.listings_found,
                error=self.error,
                metadata=self.metadata,
            )
        except Exception as metrics_error:  # pragma: no cover - defensive
            logger.error(
                f"Failed to record metrics for {self.scraper_name}: {metrics_error}"
            )

        # Do not suppress exceptions
        return False

