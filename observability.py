import json
import logging
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from utils import logger

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    return value


def _emit(record: Dict[str, Any], severity: str) -> None:
    level = _LEVELS.get(severity, logging.INFO)
    try:
        logger.log(level, json.dumps(record, default=_serialize, ensure_ascii=False))
    except Exception:
        # As a fallback, log a simplified record to avoid recursive failures
        logger.log(level, f"[OBSERVABILITY] {record.get('event_type')} {record.get('message', '')}")


def log_event(
    event_type: str,
    *,
    severity: str = "info",
    event_id: Optional[str] = None,
    **fields: Any,
) -> Dict[str, Any]:
    severity = (severity or "info").lower()
    record = {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "severity": severity,
        "timestamp": time.time(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    record.update({k: v for k, v in fields.items() if v is not None})
    _emit(record, severity)
    return record


def log_alert(
    alert_code: str,
    message: str,
    *,
    severity: str = "warning",
    **fields: Any,
) -> Dict[str, Any]:
    payload = {
        "alert_code": alert_code,
        "message": message,
    }
    payload.update(fields)
    return log_event(
        "alert",
        severity=severity if severity else "warning",
        **payload,
    )


def log_http_request(
    *,
    request_id: str,
    method: str,
    path: str,
    remote_addr: Optional[str] = None,
    user: Optional[str] = None,
    user_agent: Optional[str] = None,
    query: Optional[str] = None,
) -> Dict[str, Any]:
    return log_event(
        "http.request",
        severity="info",
        stage="start",
        request_id=request_id,
        method=method,
        path=path,
        query=query,
        user=user,
        remote_addr=remote_addr,
        user_agent=user_agent,
    )


def log_http_response(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: Optional[int] = None,
    content_length: Optional[int] = None,
    user: Optional[str] = None,
    route: Optional[str] = None,
) -> Dict[str, Any]:
    severity = "info"
    if status_code >= 500:
        severity = "error"
    elif status_code >= 400:
        severity = "warning"
    return log_event(
        "http.response",
        severity=severity,
        stage="finish",
        request_id=request_id,
        method=method,
        path=path,
        route=route,
        status_code=status_code,
        duration_ms=duration_ms,
        content_length=content_length,
        user=user,
    )

