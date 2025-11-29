# db_enhanced.py - Enhanced database module for handling 1000+ users
import sqlite3
import re
import threading
import time
import os
import json
import secrets
import string
import statistics
import hashlib
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from contextlib import contextmanager
from queue import Queue, Empty
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from error_handling import ErrorHandler, log_errors, DatabaseError
from utils import logger
from observability import log_event, log_alert

# Database configuration - supports both SQLite and PostgreSQL
DATABASE_URL = os.getenv('DATABASE_URL', '')
DB_FILE = os.getenv('DB_FILE', 'superbot.db')

# Detect database type
USE_POSTGRES = False
if DATABASE_URL and (DATABASE_URL.startswith('postgres://') or DATABASE_URL.startswith('postgresql://')):
    USE_POSTGRES = True
    try:
        import psycopg2
        from psycopg2 import pool
        from psycopg2.extras import RealDictCursor
        logger.info("PostgreSQL detected - using PostgreSQL database")
    except ImportError:
        logger.warning("DATABASE_URL points to PostgreSQL but psycopg2 not installed. Falling back to SQLite.")
        logger.warning("Install with: pip install psycopg2-binary")
        USE_POSTGRES = False
else:
    logger.info(f"Using SQLite database: {DB_FILE}")

# Profile defaults and helpers
DEFAULT_PROFILE_VISIBILITY: Dict[str, str] = {
    "display_name": "public",
    "avatar_url": "public",
    "banner_url": "connections",
    "bio": "connections",
    "location": "connections",
    "pronouns": "connections",
    "gender": "connections",
    "search_interests": "connections",
    "recent_activity": "connections",
    "showcase": "connections",
    "friends": "connections",
}

DEFAULT_SHOWCASE_CONFIG: Dict[str, List[int]] = {
    "favorite_searches": [],
    "featured_listings": [],
    "servers_joined": [],
}

PROFILE_COLLECTION_TYPES = {"favorite_searches", "featured_listings", "servers_joined"}
PROFILE_FIELD_KEYS = [
    "display_name",
    "bio",
    "avatar_url",
    "banner_url",
    "location",
    "pronouns",
    "gender",
    "search_interests",
]

SERVER_VISIBILITY_OPTIONS = {"public", "unlisted", "private"}
SERVER_DEFAULT_VISIBILITY = "public"
SERVER_MEMBERSHIP_STATUSES = {"active", "pending", "banned", "rejected"}
SERVER_CHANNEL_TYPES = {"text", "announcement", "marketplace"}
SERVER_TOPIC_TAG_LIMIT = 12
SERVER_NAME_MAX_LENGTH = 80
SERVER_DESCRIPTION_MAX_LENGTH = 800
SERVER_INVITE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SERVER_INVITE_CODE_LENGTH = 8
EMAIL_VERIFICATION_CODE_LENGTH = 6
USER_BLOCK_MAX_TARGETS = 500
FRIEND_REQUEST_THROTTLE_LIMIT = 20
FRIEND_REQUEST_THROTTLE_WINDOW_HOURS = 24

SUPPORT_TICKET_STATUSES = {"open", "in_progress", "waiting", "resolved", "closed"}
SUPPORT_TICKET_SEVERITIES = {"low", "medium", "high", "urgent"}

SUPPORT_SLA_RESPONSE_HOURS = {
    "low": 24,
    "medium": 12,
    "high": 6,
    "urgent": 2,
}

SUPPORT_SLA_RESOLUTION_HOURS = {
    "low": 72,
    "medium": 48,
    "high": 24,
    "urgent": 12,
}

DEFAULT_SERVER_ROLE_BLUEPRINT = [
    {
        "key": "owner",
        "name": "Owner",
        "permissions": {
            "manage_server": True,
            "manage_channels": True,
            "manage_roles": True,
            "manage_invites": True,
            "moderate_members": True,
            "post_announcements": True,
            "create_marketplace_drop": True,
        },
        "is_default": False,
        "sort_order": 0,
    },
    {
        "key": "moderator",
        "name": "Moderator",
        "permissions": {
            "manage_server": False,
            "manage_channels": True,
            "manage_roles": False,
            "manage_invites": True,
            "moderate_members": True,
            "post_announcements": True,
            "create_marketplace_drop": True,
        },
        "is_default": False,
        "sort_order": 1,
    },
    {
        "key": "member",
        "name": "Member",
        "permissions": {
            "manage_server": False,
            "manage_channels": False,
            "manage_roles": False,
            "manage_invites": False,
            "moderate_members": False,
            "post_announcements": False,
            "create_marketplace_drop": True,
        },
        "is_default": True,
        "sort_order": 2,
    },
]

DEFAULT_SERVER_CHANNEL_BLUEPRINT = [
    {
        "type": "announcement",
        "name": "Announcements",
        "slug": "announcements",
        "topic": "Official updates and news",
        "position": 1,
        "settings": {"slow_mode": 60, "posting_roles": ["owner", "moderator"]},
    },
    {
        "type": "text",
        "name": "general",
        "slug": "general",
        "topic": "Main discussion",
        "position": 2,
        "settings": {"slow_mode": 0},
    },
    {
        "type": "marketplace",
        "name": "marketplace",
        "slug": "marketplace",
        "topic": "Drops, deals, and trades",
        "position": 3,
        "settings": {"slow_mode": 0},
    },
]

FEED_AUDIENCE_TYPES = {"global", "user", "server"}
NOTIFICATION_STATUS_STATES = {"in_app", "queued", "sent", "dismissed", "read"}

SERVER_OWNER_DIGEST_STATUS_PENDING = "pending"
SERVER_OWNER_DIGEST_STATUS_DELIVERED = "delivered"
SERVER_OWNER_DIGEST_STATUS_FAILED = "failed"
SERVER_OWNER_DIGEST_STATUSES = {
    SERVER_OWNER_DIGEST_STATUS_PENDING,
    SERVER_OWNER_DIGEST_STATUS_DELIVERED,
    SERVER_OWNER_DIGEST_STATUS_FAILED,
}
SERVER_OWNER_DIGEST_DEFAULT_CHANNEL = "email"
SERVER_OWNER_DIGEST_MAX_PERIOD_DAYS = 90

MODERATION_REPORT_SPIKE_WINDOW_MINUTES = 30
MODERATION_REPORT_SPIKE_RECENT_MINUTES = 15
MODERATION_REPORT_SPIKE_OPEN_THRESHOLD = 5
MODERATION_REPORT_SPIKE_RECENT_THRESHOLD = 3
MODERATION_SLOW_MODE_WINDOW_MINUTES = 10
MODERATION_SLOW_MODE_THRESHOLD = 3

REFERRAL_CODE_ALPHABET = string.ascii_uppercase + string.digits
REFERRAL_CODE_LENGTH = 8
REFERRAL_MAX_HITS_FETCH = 10
REFERRAL_MAX_LANDING_SUMMARY = 5

BOOST_STATUS_ACTIVE = "active"
BOOST_STATUS_EXPIRED = "expired"
BOOST_STATUS_CANCELLED = "cancelled"
BOOST_MAX_DURATION_DAYS = 90

MODERATION_SUGGESTION_STOPWORDS = {
    "this",
    "that",
    "with",
    "from",
    "there",
    "their",
    "them",
    "have",
    "about",
    "please",
    "thanks",
    "thank",
    "http",
    "https",
    "www",
    "com",
    "user",
    "report",
    "spam",
    "message",
    "channel",
    "server",
    "people",
    "someone",
    "being",
    "like",
    "just",
    "still",
    "your",
    "you're",
    "they're",
    "want",
    "know",
    "need",
    "please",
}

FRIEND_REQUEST_STATUS_PENDING = "pending"
FRIEND_REQUEST_STATUS_ACCEPTED = "accepted"
FRIEND_REQUEST_STATUS_DECLINED = "declined"
FRIEND_REQUEST_STATUS_CANCELLED = "cancelled"
FRIEND_REQUEST_STATUSES = {
    FRIEND_REQUEST_STATUS_PENDING,
    FRIEND_REQUEST_STATUS_ACCEPTED,
    FRIEND_REQUEST_STATUS_DECLINED,
    FRIEND_REQUEST_STATUS_CANCELLED,
}
FRIEND_REQUEST_MESSAGE_MAX_LENGTH = 140

REPORT_STATUS_PENDING = "pending"
REPORT_STATUS_REVIEWING = "reviewing"
REPORT_STATUS_RESOLVED = "resolved"
REPORT_STATUS_DISMISSED = "dismissed"
REPORT_STATUSES = {
    REPORT_STATUS_PENDING,
    REPORT_STATUS_REVIEWING,
    REPORT_STATUS_RESOLVED,
    REPORT_STATUS_DISMISSED,
}
KEYWORD_FILTER_ALLOWED_ACTIONS = {"block", "warn", "flag"}
KEYWORD_FILTER_MAX_PHRASE_LENGTH = 120


def _load_json(value: Optional[str], default: Any):
    if value in (None, "", b""):
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _dump_json(value: Any) -> str:
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        # Fallback to empty JSON object to avoid raising in DB write path
        if isinstance(value, list):
            return "[]"
        return "{}"


def _profile_default_visibility() -> Dict[str, str]:
    return dict(DEFAULT_PROFILE_VISIBILITY)


def _profile_default_showcase() -> Dict[str, List[int]]:
    return {
        "favorite_searches": [],
        "featured_listings": [],
        "servers_joined": [],
    }


def _merge_visibility_defaults(visibility: Optional[Dict[str, Any]]) -> Dict[str, str]:
    merged = _profile_default_visibility()
    if isinstance(visibility, dict):
        for key, value in visibility.items():
            if key not in merged:
                continue
            option = str(value).lower()
            if option in {"public", "connections", "private"}:
                merged[key] = option
    return merged


def _merge_showcase_defaults(config: Optional[Dict[str, Any]]) -> Dict[str, List[Any]]:
    merged = dict(_profile_default_showcase())
    if isinstance(config, dict):
        for key, items in config.items():
            if key not in merged:
                continue
            if isinstance(items, list):
                merged[key] = items
    return merged


def _sanitize_search_interests(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []

    normalized: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for entry in value:
        if isinstance(entry, str):
            label = entry.strip()
            if not label:
                continue
            identifier = _slugify(label, fallback=label[:32])
            if identifier in seen:
                continue
            seen.add(identifier)
            normalized.append({
                "id": identifier,
                "label": label,
                "category": None,
            })
            continue

        if not isinstance(entry, dict):
            continue

        label = str(entry.get("label") or entry.get("name") or "").strip()
        identifier = str(entry.get("id") or entry.get("slug") or _slugify(label or str(entry.get("value") or ""), fallback="interest"))
        if not identifier:
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        category = entry.get("category")
        if category is not None:
            category = str(category).strip() or None
        normalized.append({
            "id": identifier,
            "label": label or identifier,
            "category": category,
        })

    return normalized


_slug_pattern = re.compile(r"[^a-z0-9]+")


def _slugify(value: str, fallback: str = "item") -> str:
    if value is None:
        value = ""
    normalized = _slug_pattern.sub("-", value.lower()).strip("-")
    if not normalized:
        return fallback
    return normalized[:64]


def _parse_db_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value)
        except (OverflowError, ValueError):
            return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _normalize_topic_tags(raw_tags: Optional[Any]) -> List[Dict[str, str]]:
    if raw_tags is None:
        return []

    tags: List[Dict[str, str]] = []
    seen: set[str] = set()

    if isinstance(raw_tags, str):
        candidates = [part.strip() for part in raw_tags.split(",")]
    else:
        candidates = list(raw_tags) if isinstance(raw_tags, (list, tuple, set)) else []

    for item in candidates:
        label = ""
        if isinstance(item, dict):
            label = (item.get("label") or item.get("name") or "").strip()
        else:
            label = str(item or "").strip()

        if not label:
            continue

        slug = _slugify(label, fallback="tag")
        if slug in seen:
            continue
        seen.add(slug)

        tags.append({
            "label": label[:60],
            "slug": slug,
        })

        if len(tags) >= SERVER_TOPIC_TAG_LIMIT:
            break

    return tags


def _generate_unique_server_slug(name: str, preferred_slug: Optional[str] = None) -> str:
    base = _slugify(preferred_slug or name, fallback="server")
    slug_candidate = base
    suffix = 2

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        while True:
            c.execute("SELECT 1 FROM servers WHERE slug = ?", (slug_candidate,))
            if not c.fetchone():
                return slug_candidate
            slug_candidate = f"{base}-{suffix}"
            suffix += 1


def _generate_invite_code() -> str:
    alphabet = SERVER_INVITE_CODE_ALPHABET
    return "".join(secrets.choice(alphabet) for _ in range(SERVER_INVITE_CODE_LENGTH))


def generate_verification_code(length: int = EMAIL_VERIFICATION_CODE_LENGTH) -> str:
    """Generate a numeric verification code with the configured length."""
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(max(4, length)))


def hash_verification_code(username: str, code: str) -> str:
    """Create a deterministic hash for a verification code scoped to the user."""
    normalized_username = (username or "").strip().lower()
    normalized_code = (code or "").strip()
    payload = f"{normalized_username}:{normalized_code}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _server_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    topic_tags = _load_json(row[5], [])
    settings = _load_json(row[9], {})

    created_at_idx = 10 if len(row) > 10 else None
    updated_at_idx = 11 if len(row) > 11 else None

    return {
        "id": row[0],
        "owner_username": row[1],
        "name": row[2],
        "slug": row[3],
        "description": row[4],
        "topic_tags": topic_tags if isinstance(topic_tags, list) else [],
        "visibility": row[6] or SERVER_DEFAULT_VISIBILITY,
        "icon_url": row[7],
        "banner_url": row[8],
        "settings": settings if isinstance(settings, dict) else {},
        "created_at": _to_datetime_string(row[created_at_idx]) if created_at_idx is not None else None,
        "updated_at": _to_datetime_string(row[updated_at_idx]) if updated_at_idx is not None else None,
    }


def _serialize_membership_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    membership = {
        "server_id": row[0],
        "username": row[1],
        "role_id": row[2],
        "status": row[3],
        "invited_by": row[4],
        "invite_code": row[5],
        "requested_at": _to_datetime_string(row[6]),
        "joined_at": _to_datetime_string(row[7]),
        "last_active_at": _to_datetime_string(row[8]),
        "reviewed_at": _to_datetime_string(row[9]),
        "reviewed_by": row[10],
    }
    if len(row) > 11:
        membership["role_name"] = row[11]
    if len(row) > 12:
        membership["permissions"] = _load_json(row[12], {})
    return membership


def _prepare_sql(statement):
    """Translate SQLite-specific SQL to PostgreSQL-compatible SQL when needed."""
    if not USE_POSTGRES or not isinstance(statement, str):
        return statement

    replacements = [
        ("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"),
        ("DATETIME", "TIMESTAMP"),
        ("BOOLEAN DEFAULT 0", "BOOLEAN DEFAULT FALSE"),
        ("BOOLEAN DEFAULT 1", "BOOLEAN DEFAULT TRUE"),
        ("BOOLEAN DEFAULT '0'", "BOOLEAN DEFAULT FALSE"),
        ("BOOLEAN DEFAULT '1'", "BOOLEAN DEFAULT TRUE"),
        ("BOOLEAN DEFAULT \"0\"", "BOOLEAN DEFAULT FALSE"),
        ("BOOLEAN DEFAULT \"1\"", "BOOLEAN DEFAULT TRUE"),
        ("REAL", "DOUBLE PRECISION"),
    ]

    converted = statement
    for old, new in replacements:
        converted = converted.replace(old, new)

    stripped = converted.lstrip()
    if stripped.upper().startswith("ALTER TABLE"):
        converted = re.sub(
            r"ADD COLUMN(?!\s+IF\s+NOT\s+EXISTS)",
            "ADD COLUMN IF NOT EXISTS",
            converted,
            flags=re.IGNORECASE
        )

    if "?" in converted:
        # Replace SQLite-style positional placeholders with psycopg2 ones.
        parts = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")", converted)
        for idx, part in enumerate(parts):
            if idx % 2 == 0:  # outside quoted strings
                parts[idx] = part.replace("?", "%s")
        converted = "".join(parts)

    return converted

def _should_ignore_duplicate_error(error):
    """Return True when duplicate column/index errors can be safely ignored."""
    message = str(error).lower()
    if "already exists" in message or "duplicate column" in message:
        return True
    if USE_POSTGRES:
        pgcode = getattr(error, "pgcode", None)
        if pgcode in {"42701", "42P07"}:  # duplicate_column, duplicate_table
            return True
    return False

def _ignore_duplicate_schema_error(conn, error):
    """
    Normalize duplicate schema errors across SQLite/PostgreSQL.
    Returns True when the error can be ignored safely.
    """
    if _should_ignore_duplicate_error(error):
        if USE_POSTGRES:
            try:
                conn.rollback()
            except Exception:
                pass
        return True
    return False


def _to_datetime_string(value):
    """Normalize datetime values to ISO strings for consistent API responses."""
    if isinstance(value, datetime):
        try:
            return value.isoformat(sep=' ', timespec='seconds')
        except TypeError:
            return value.isoformat()
    return value


def _user_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    """Convert a raw users row into a normalized dictionary."""
    if not row:
        return {}

    length = len(row)
    return {
        "id": row[0] if length > 0 else None,
        "username": row[1] if length > 1 else None,
        "email": row[2] if length > 2 else None,
        "password": row[3] if length > 3 else None,
        "role": row[4] if length > 4 else "user",
        "verified": bool(row[5]) if length > 5 and row[5] is not None else False,
        "active": bool(row[6]) if length > 6 and row[6] is not None else True,
        "created_at": _to_datetime_string(row[7]) if length > 7 else None,
        "last_login": _to_datetime_string(row[8]) if length > 8 else None,
        "login_count": row[9] if length > 9 and row[9] is not None else 0,
        "phone_number": row[10] if length > 10 else None,
        "email_notifications": bool(row[11]) if length > 11 and row[11] is not None else True,
        "sms_notifications": bool(row[12]) if length > 12 and row[12] is not None else False,
        "tos_agreed": bool(row[13]) if length > 13 and row[13] is not None else False,
        "tos_agreed_at": _to_datetime_string(row[14]) if length > 14 else None,
    }


def _profile_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    """Normalize a profiles table row into a structured dictionary."""
    if not row:
        return {}

    length = len(row)
    showcase_raw = row[10] if length > 10 else None
    visibility_raw = row[11] if length > 11 else None
    interests_raw = row[9] if length > 9 else "[]"

    search_interests = _sanitize_search_interests(_load_json(interests_raw, []))
    showcase = _merge_showcase_defaults(_load_json(showcase_raw, {}))
    visibility = _merge_visibility_defaults(_load_json(visibility_raw, {}))

    return {
        "id": row[0] if length > 0 else None,
        "username": row[1] if length > 1 else None,
        "display_name": row[2] if length > 2 and row[2] else (row[1] if length > 1 else None),
        "bio": row[3] if length > 3 else None,
        "avatar_url": row[4] if length > 4 else None,
        "banner_url": row[5] if length > 5 else None,
        "gender": row[6] if length > 6 else None,
        "pronouns": row[7] if length > 7 else None,
        "location": row[8] if length > 8 else None,
        "search_interests": search_interests,
        "showcase_config": showcase,
        "visibility_settings": visibility,
        "created_at": _to_datetime_string(row[12]) if length > 12 else None,
        "updated_at": _to_datetime_string(row[13]) if length > 13 else None,
    }


def _support_ticket_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    if not row:
        return {}

    metadata = _load_json(row[18], {})
    server_info = None
    if row[1]:
        server_info = {
            "id": row[1],
            "slug": row[2],
            "name": row[3],
            "owner_username": row[4],
        }

    return {
        "id": row[0],
        "server_id": row[1],
        "server": server_info,
        "reporter_username": row[5],
        "subject": row[6],
        "body": row[7],
        "status": row[8],
        "severity": row[9],
        "assigned_to": row[10],
        "related_report_id": row[11],
        "related_digest_id": row[12],
        "first_response_at": _to_datetime_string(row[13]),
        "resolved_at": _to_datetime_string(row[14]),
        "created_at": _to_datetime_string(row[15]),
        "updated_at": _to_datetime_string(row[16]),
        "last_activity_at": _to_datetime_string(row[17]),
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


def _support_ticket_event_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    if not row:
        return {}

    metadata = _load_json(row[5], {})
    return {
        "id": row[0],
        "ticket_id": row[1],
        "actor_username": row[2],
        "event_type": row[3],
        "comment": row[4],
        "metadata": metadata if isinstance(metadata, dict) else {},
        "created_at": _to_datetime_string(row[6]),
    }


_SUPPORT_TICKET_SELECT_BASE = """
    SELECT t.id,
           t.server_id,
           s.slug,
           s.name,
           s.owner_username,
           t.reporter_username,
           t.subject,
           t.body,
           t.status,
           t.severity,
           t.assigned_to,
           t.related_report_id,
           t.related_digest_id,
           t.first_response_at,
           t.resolved_at,
           t.created_at,
           t.updated_at,
           t.last_activity_at,
           t.metadata
    FROM support_tickets t
    LEFT JOIN servers s ON s.id = t.server_id
"""


def _select_support_ticket_row(cursor: sqlite3.Cursor, ticket_id: int) -> Optional[Tuple[Any, ...]]:
    cursor.execute(_prepare_sql(_SUPPORT_TICKET_SELECT_BASE + " WHERE t.id = ?"), (ticket_id,))
    return cursor.fetchone()


def _select_support_ticket_events(cursor: sqlite3.Cursor, ticket_id: int, limit: Optional[int] = None) -> List[Tuple[Any, ...]]:
    sql = """
        SELECT id,
               ticket_id,
               actor_username,
               event_type,
               comment,
               metadata,
               created_at
        FROM support_ticket_events
        WHERE ticket_id = ?
        ORDER BY created_at DESC, id DESC
    """
    params: List[Any] = [ticket_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    cursor.execute(_prepare_sql(sql), tuple(params))
    return cursor.fetchall()


def _is_admin_user(username: Optional[str]) -> bool:
    if not username:
        return False
    try:
        user = get_user_by_username(username)
    except Exception:
        return False
    if not user:
        return False
    return str(user.get("role") or "").lower() == "admin"


def _normalize_ticket_status(status: Optional[str]) -> str:
    normalized = (status or "").strip().lower()
    if not normalized:
        raise ValueError("status is required")
    if normalized not in SUPPORT_TICKET_STATUSES:
        raise ValueError("Invalid ticket status")
    return normalized


def _normalize_ticket_severity(severity: Optional[str]) -> str:
    normalized = (severity or "medium").strip().lower()
    if normalized not in SUPPORT_TICKET_SEVERITIES:
        raise ValueError("Invalid ticket severity")
    return normalized


def _user_can_view_ticket(ticket: Dict[str, Any], username: Optional[str]) -> bool:
    if not username:
        return False
    if _is_admin_user(username):
        return True
    if ticket.get("reporter_username") == username:
        return True
    if ticket.get("assigned_to") == username:
        return True
    server = ticket.get("server") or {}
    if server.get("owner_username") == username:
        return True
    return False


def _user_can_update_ticket(ticket: Dict[str, Any], username: Optional[str]) -> bool:
    if not username:
        return False
    if _is_admin_user(username):
        return True
    server = ticket.get("server") or {}
    if server.get("owner_username") == username:
        return True
    if ticket.get("assigned_to") == username:
        return True
    return False


def _user_can_comment_ticket(ticket: Dict[str, Any], username: Optional[str]) -> bool:
    return _user_can_view_ticket(ticket, username)


def _merge_ticket_metadata(existing: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing or {})
    for key, value in (updates or {}).items():
        merged[key] = value
    return merged


def _record_ticket_event(cursor: sqlite3.Cursor,
                         ticket: Dict[str, Any],
                         actor_username: Optional[str],
                         event_type: str,
                         comment: Optional[str] = None,
                         metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    now = datetime.now()
    cursor.execute(_prepare_sql("""
        INSERT INTO support_ticket_events (ticket_id, actor_username, event_type, comment, metadata, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """), (
        ticket["id"],
        actor_username,
        event_type,
        comment,
        _dump_json(metadata if isinstance(metadata, dict) else {}),
        now,
    ))
    event_id = cursor.lastrowid

    update_fields = ["last_activity_at = ?", "updated_at = ?"]
    update_params: List[Any] = [now, now]
    if actor_username and actor_username != ticket.get("reporter_username") and not ticket.get("first_response_at"):
        update_fields.append("first_response_at = ?")
        update_params.append(now)
        ticket["first_response_at"] = _to_datetime_string(now)

    cursor.execute(_prepare_sql(f"""
        UPDATE support_tickets
        SET {', '.join(update_fields)}
        WHERE id = ?
    """), (*update_params, ticket["id"]))

    ticket["last_activity_at"] = _to_datetime_string(now)
    ticket["updated_at"] = _to_datetime_string(now)

    cursor.execute("""
        SELECT id,
               ticket_id,
               actor_username,
               event_type,
               comment,
               metadata,
               created_at
        FROM support_ticket_events
        WHERE id = ?
    """, (event_id,))
    return _support_ticket_event_row_to_dict(cursor.fetchone())


class _PostgresCursorWrapper:
    """Cursor proxy that normalizes SQLite DDL to PostgreSQL syntax."""

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, statement, *args, **kwargs):
        statement = _prepare_sql(statement)
        return self._cursor.execute(statement, *args, **kwargs)

    def executemany(self, statement, seq_of_params):
        statement = _prepare_sql(statement)
        return self._cursor.executemany(statement, seq_of_params)

    def __getattr__(self, item):
        return getattr(self._cursor, item)

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._cursor.__exit__(exc_type, exc_val, exc_tb)


class _PostgresConnectionWrapper:
    """Connection proxy that emulates sqlite3 connection helpers for PostgreSQL."""

    def __init__(self, connection):
        self._connection = connection

    def cursor(self, *args, **kwargs):
        cursor = self._connection.cursor(*args, **kwargs)
        return _PostgresCursorWrapper(cursor)

    def execute(self, statement, *args, **kwargs):
        cursor = self.cursor()
        try:
            cursor.execute(statement, *args, **kwargs)
        except Exception:
            try:
                cursor.close()
            except Exception:
                pass
            raise
        return cursor

    def executemany(self, statement, seq_of_params):
        cursor = self.cursor()
        try:
            cursor.executemany(statement, seq_of_params)
        except Exception:
            try:
                cursor.close()
            except Exception:
                pass
            raise
        return cursor

    def __getattr__(self, item):
        return getattr(self._connection, item)

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._connection.__exit__(exc_type, exc_val, exc_tb)


# Connection pool configuration - optimized for production
POOL_SIZE = 5  # Reduced pool size for better memory management
CONNECTION_TIMEOUT = 10  # Reduced timeout for faster failure detection

# Async activity logging queue to prevent blocking on login
_activity_log_queue = Queue(maxsize=2000)
_activity_logger_thread = None
_activity_logger_running = False

def _activity_logger_worker():
    """Background thread that processes activity log events from queue"""
    global _activity_logger_running
    logger.info("Activity logger worker started")
    
    while _activity_logger_running:
        try:
            # Wait for events with timeout to allow clean shutdown
            event_data = _activity_log_queue.get(timeout=1)
            
            # Try to log to database with limited retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    if event_data['type'] == 'login':
                        # Update login tracking and log activity
                        _update_user_login_and_log_activity_sync(
                            event_data['username'],
                            event_data.get('ip_address'),
                            event_data.get('user_agent')
                        )
                    elif event_data['type'] == 'activity':
                        # Log general activity
                        _log_user_activity_sync(
                            event_data['username'],
                            event_data['action'],
                            event_data.get('details'),
                            event_data.get('ip_address'),
                            event_data.get('user_agent')
                        )
                    break  # Success
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.1 * (2 ** attempt))  # Exponential backoff
                    else:
                        # Failed all retries, log to file
                        logger.warning(
                            f"Failed to log activity after {max_retries} attempts: "
                            f"Type={event_data['type']}, Username={event_data.get('username')}"
                        )
            
            _activity_log_queue.task_done()
            
        except Empty:
            # Queue timeout, continue loop
            continue
        except Exception as e:
            logger.error(f"Activity logger worker error: {e}")
    
    logger.info("Activity logger worker stopped")

def start_activity_logger():
    """Start the background activity logger thread"""
    global _activity_logger_thread, _activity_logger_running
    
    if _activity_logger_running:
        return  # Already running
    
    _activity_logger_running = True
    _activity_logger_thread = threading.Thread(target=_activity_logger_worker, daemon=True)
    _activity_logger_thread.start()
    logger.info("Activity logger background thread started")

def stop_activity_logger():
    """Stop the background activity logger thread"""
    global _activity_logger_running
    
    if not _activity_logger_running:
        return
    
    _activity_logger_running = False
    if _activity_logger_thread:
        _activity_logger_thread.join(timeout=5)
    logger.info("Activity logger background thread stopped")


class DatabaseConnectionPool:
    """Thread-safe connection pool for SQLite"""
    
    def __init__(self, database, pool_size=POOL_SIZE):
        self.database = database
        self.pool_size = pool_size
        self.pool = Queue(maxsize=pool_size)
        self.all_connections = []
        self.lock = threading.Lock()
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize the connection pool"""
        for _ in range(self.pool_size):
            conn = self._create_connection()
            self.pool.put(conn)
            self.all_connections.append(conn)
        logger.info(f"Initialized database connection pool with {self.pool_size} connections")
    
    def _create_connection(self):
        """Create a new database connection with optimal settings"""
        conn = sqlite3.connect(
            self.database,
            check_same_thread=False,
            timeout=CONNECTION_TIMEOUT,
            isolation_level=None  # Autocommit mode to reduce locking
        )
        # Production-optimized pragmas for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=20000")  # Increased cache size
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        conn.execute("PRAGMA busy_timeout=2000")  # 2 second timeout for faster failure detection
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA read_uncommitted=1")  # Allow dirty reads for better concurrency
        conn.execute("PRAGMA locking_mode=NORMAL")  # Use normal locking
        # WAL checkpoint optimization
        conn.execute("PRAGMA wal_autocheckpoint=1000")  # More frequent checkpoints
        # Enable query planner optimizations
        conn.execute("PRAGMA optimize")
        return conn
    
    @contextmanager
    def get_connection(self):
        """Get a connection from the pool (context manager)"""
        conn = None
        try:
            conn = self.pool.get(timeout=CONNECTION_TIMEOUT)
            # Test the connection before yielding
            try:
                conn.execute("SELECT 1").fetchone()
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e).lower():
                    # Create a new connection if the pooled one is locked
                    logger.warning("Pooled connection is locked, creating new connection")
                    conn.close()
                    conn = self._create_connection()
                else:
                    # For other errors, close and create new connection
                    logger.warning(f"Connection test failed: {e}, creating new connection")
                    conn.close()
                    conn = self._create_connection()
            yield conn
        except Empty:
            logger.error("Connection pool exhausted - consider increasing pool size")
            raise DatabaseError("Database connection pool exhausted")
        finally:
            if conn:
                try:
                    # Ensure connection is in a good state before returning to pool
                    conn.execute("SELECT 1").fetchone()
                    self.pool.put(conn)
                except sqlite3.OperationalError:
                    # If connection is bad, close it and don't return to pool
                    logger.warning("Removing bad connection from pool")
                    conn.close()
    
    def close_all(self):
        """Close all connections in the pool"""
        with self.lock:
            for conn in self.all_connections:
                try:
                    conn.close()
                except Exception as e:
                    logger.error(f"Error closing connection: {e}")
            self.all_connections.clear()
            logger.info("Closed all database connections")
# PostgreSQL connection pool class
class PostgreSQLConnectionPool:
    """Thread-safe connection pool for PostgreSQL"""
    
    def __init__(self, database_url, pool_size=POOL_SIZE):
        from psycopg2.pool import ThreadedConnectionPool
        import threading
        self.database_url = database_url
        self.pool_size = pool_size
        self.lock = threading.Lock()
        self.all_connections = []
        try:
            self.pool = ThreadedConnectionPool(1, pool_size, database_url)
            logger.info(f"Initialized PostgreSQL connection pool with {pool_size} max connections")
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL connection pool: {e}")
            raise DatabaseError(f"Failed to initialize PostgreSQL pool: {e}")
    
    @contextmanager
    def get_connection(self, timeout=CONNECTION_TIMEOUT):
        """Get a connection from the pool (context manager)"""
        from psycopg2.pool import PoolError

        if timeout is None:
            timeout = CONNECTION_TIMEOUT

        conn = None
        proxy = None
        start_time = time.time()

        while True:
            try:
                conn = self.pool.getconn()
                if conn is None:
                    raise DatabaseError("Failed to get connection from PostgreSQL pool")

                # Align transaction behavior with SQLite autocommit mode
                if hasattr(conn, "autocommit") and not conn.autocommit:
                    conn.autocommit = True

                proxy = _PostgresConnectionWrapper(conn)

                # Test connection viability
                cursor = proxy.cursor()
                try:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                finally:
                    try:
                        cursor.close()
                    except Exception:
                        pass
                break
            except PoolError as pool_error:
                if timeout > 0 and (time.time() - start_time) < timeout:
                    time.sleep(0.1)
                    continue
                logger.error(f"PostgreSQL connection pool exhausted: {pool_error}")
                raise DatabaseError(f"PostgreSQL connection failed: {pool_error}")
            except Exception as e:
                if conn:
                    try:
                        self.pool.putconn(conn, close=True)
                    except Exception:
                        try:
                            conn.close()
                        except Exception:
                            pass
                    conn = None

                if timeout > 0 and (time.time() - start_time) < timeout:
                    time.sleep(0.1)
                    continue

                logger.error(f"PostgreSQL connection error: {e}")
                raise DatabaseError(f"PostgreSQL connection failed: {e}")

        if proxy is None:
            proxy = _PostgresConnectionWrapper(conn)

        try:
            yield proxy
        finally:
            raw_conn = proxy._connection if proxy else conn
            if raw_conn:
                try:
                    self.pool.putconn(raw_conn)
                except Exception as e:
                    logger.error(f"Error returning connection to pool: {e}")
                    try:
                        self.pool.putconn(raw_conn, close=True)
                    except Exception:
                        try:
                            raw_conn.close()
                        except Exception:
                            pass
    
    def close_all(self):
        """Close all connections in the pool"""
        if hasattr(self, 'pool') and self.pool:
            try:
                self.pool.closeall()
                logger.info("Closed all PostgreSQL connections")
            except Exception as e:
                logger.error(f"Error closing PostgreSQL pool: {e}")


# Global connection pool
_connection_pool = None


def get_pool():
    """Get or create the global connection pool"""
    global _connection_pool
    if _connection_pool is None:
        if USE_POSTGRES:
            # PostgreSQL support - create PostgreSQL pool
            try:
                from psycopg2.pool import ThreadedConnectionPool
                _connection_pool = PostgreSQLConnectionPool(DATABASE_URL)
                logger.info("✅ Using PostgreSQL - user data will persist across deployments")
            except Exception as e:
                logger.error(f"Failed to create PostgreSQL pool: {e}")
                logger.warning("⚠️  Falling back to SQLite - user data will NOT persist on deployments")
                logger.warning("⚠️  See docs/deployment/DATABASE_PERSISTENCE_SETUP.md for setup instructions")
                _connection_pool = DatabaseConnectionPool(DB_FILE)
        else:
            logger.warning("⚠️  Using SQLite - user data will NOT persist on deployments")
            logger.warning("⚠️  Set DATABASE_URL to use PostgreSQL for persistent storage")
            _connection_pool = DatabaseConnectionPool(DB_FILE)
    return _connection_pool

def maintain_database():
    """Perform database maintenance to prevent locking issues"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            if USE_POSTGRES:
                c.execute("ANALYZE")
            else:
                # Analyze database for better query planning
                c.execute("ANALYZE")
                # Clean up any pending transactions
                c.execute("PRAGMA optimize")
                # Check database integrity
                c.execute("PRAGMA integrity_check")
            try:
                conn.commit()
            except Exception:
                pass
            logger.info("Database maintenance completed")
    except Exception as e:
        logger.error(f"Database maintenance failed: {e}")

def get_pool_status():
    """Get current pool status for monitoring"""
    try:
        pool = get_pool()
        return {
            "pool_size": pool.pool_size,
            "available_connections": pool.pool.qsize(),
            "total_connections": len(pool.all_connections),
            "pool_utilization": f"{((pool.pool_size - pool.pool.qsize()) / pool.pool_size) * 100:.1f}%"
        }
    except Exception as e:
        logger.error(f"Failed to get pool status: {e}")
        return {"error": str(e)}

def cleanup_old_connections():
    """Clean up old or problematic connections from the pool"""
    try:
        pool = get_pool()
        if USE_POSTGRES and isinstance(pool, PostgreSQLConnectionPool):
            logger.info("Skipping SQLite-style connection cleanup for PostgreSQL pool")
            return
        with pool.lock:
            # Test all connections and remove bad ones
            good_connections = []
            for conn in pool.all_connections:
                try:
                    conn.execute("SELECT 1").fetchone()
                    good_connections.append(conn)
                except Exception:
                    conn.close()
                    logger.warning("Removed bad connection from pool")
            
            # Rebuild the pool with good connections
            pool.all_connections = good_connections
            pool.pool = Queue(maxsize=pool.pool_size)
            for conn in good_connections:
                pool.pool.put(conn)
            
            logger.info(f"Cleaned up connection pool, {len(good_connections)} connections remaining")
    except Exception as e:
        logger.error(f"Connection cleanup failed: {e}")

def reset_connection_pool():
    """Reset the entire connection pool when locking issues persist"""
    try:
        global _connection_pool
        if _connection_pool:
            logger.warning("Resetting connection pool due to persistent locking issues")
            _connection_pool.close_all()
            _connection_pool = None
        
        # Create a new pool
        if USE_POSTGRES:
            _connection_pool = PostgreSQLConnectionPool(DATABASE_URL)
        else:
            _connection_pool = DatabaseConnectionPool(DB_FILE)
        logger.info("Connection pool reset successfully")
    except Exception as e:
        logger.error(f"Connection pool reset failed: {e}")


def retry_db_operation(operation_func, max_retries=5, base_delay=0.1):
    """
    Retry database operations with exponential backoff for handling locking issues
    
    Args:
        operation_func: Function to execute (should return a result)
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff
    
    Returns:
        Result of the operation or None if all retries failed
    """
    import time
    import random
    
    for attempt in range(max_retries):
        try:
            return operation_func()
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "database table is locked" in error_msg:
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.2)
                    logger.warning(f"Database locked, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Database locked after {max_retries} attempts")
                    # Try to reset connection pool on final failure
                    try:
                        reset_connection_pool()
                    except Exception as reset_error:
                        logger.error(f"Connection pool reset failed: {reset_error}")
                    return None
            elif "database is busy" in error_msg:
                if attempt < max_retries - 1:
                    # Shorter delay for busy database
                    delay = base_delay * (1.5 ** attempt) + random.uniform(0, 0.1)
                    logger.warning(f"Database busy, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Database busy after {max_retries} attempts")
                    return None
            else:
                logger.error(f"Database error: {e}")
                return None
        except sqlite3.DatabaseError as e:
            logger.error(f"Database integrity error: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in database operation: {e}")
            return None
    
    logger.warning(f"Database operation failed after {max_retries} attempts")
    return None


@log_errors()
def init_db():
    """Initialize database with all required tables and indexes"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            if USE_POSTGRES:
                c = _PostgresCursorWrapper(c)
            
            # Users table with enhanced fields
            c.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    role TEXT DEFAULT 'user',
                    verified BOOLEAN DEFAULT 0,
                    active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_login DATETIME,
                    login_count INTEGER DEFAULT 0,
                    phone_number TEXT,
                    email_notifications BOOLEAN DEFAULT 1,
                    sms_notifications BOOLEAN DEFAULT 0
                )
            """)
            
            # Add notification columns if they don't exist (for existing databases)
            try:
                c.execute("ALTER TABLE users ADD COLUMN phone_number TEXT")
                logger.info("Added phone_number column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN tos_agreed BOOLEAN DEFAULT 0")
                logger.info("Added tos_agreed column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN tos_agreed_at DATETIME")
                logger.info("Added tos_agreed_at column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN email_notifications BOOLEAN DEFAULT 1")
                logger.info("Added email_notifications column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE users ADD COLUMN sms_notifications BOOLEAN DEFAULT 0")
                logger.info("Added sms_notifications column to users table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise

            # Extended profile tables
            c.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    display_name TEXT,
                    bio TEXT,
                    avatar_url TEXT,
                    banner_url TEXT,
                    gender TEXT,
                    pronouns TEXT,
                    location TEXT,
                    search_interests TEXT,
                    showcase_config TEXT,
                    visibility_settings TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS profile_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    activity_type TEXT NOT NULL,
                    entity_id TEXT,
                    metadata TEXT,
                    occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS profile_showcase_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    collection_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    label TEXT,
                    position INTEGER DEFAULT 0,
                    metadata TEXT,
                    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_profile_activity_user
                ON profile_activity (username, occurred_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_profile_showcase_user_collection
                ON profile_showcase_items (username, collection_type, position)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS profile_contacts (
                    owner_username TEXT NOT NULL,
                    contact_username TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (owner_username, contact_username),
                    FOREIGN KEY (owner_username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (contact_username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_profile_contacts_owner
                ON profile_contacts (owner_username, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS friend_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requester_username TEXT NOT NULL,
                    recipient_username TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    responded_at DATETIME,
                    FOREIGN KEY (requester_username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (recipient_username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_friend_requests_recipient_status
                ON friend_requests (recipient_username, status, created_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_friend_requests_requester_status
                ON friend_requests (requester_username, status, created_at DESC)
            """)

            try:
                c.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_friend_requests_pending_unique
                    ON friend_requests (requester_username, recipient_username)
                    WHERE status = 'pending'
                """)
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise

            c.execute("""
                CREATE TABLE IF NOT EXISTS friendships (
                    owner_username TEXT NOT NULL,
                    friend_username TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    source_request_id INTEGER,
                    PRIMARY KEY (owner_username, friend_username),
                    FOREIGN KEY (owner_username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (friend_username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (source_request_id) REFERENCES friend_requests (id) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_friendships_owner_created
                ON friendships (owner_username, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS user_blocks (
                    owner_username TEXT NOT NULL,
                    blocked_username TEXT NOT NULL,
                    reason TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (owner_username, blocked_username),
                    FOREIGN KEY (owner_username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (blocked_username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_blocks_blocked
                ON user_blocks (blocked_username, owner_username)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS friend_request_throttle (
                    username TEXT PRIMARY KEY,
                    window_start DATETIME NOT NULL,
                    request_count INTEGER NOT NULL,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            # Community servers
            c.execute("""
                CREATE TABLE IF NOT EXISTS servers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    description TEXT,
                    topic_tags TEXT,
                    visibility TEXT DEFAULT 'public',
                    icon_url TEXT,
                    banner_url TEXT,
                    settings TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (owner_username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_servers_visibility_created
                ON servers (visibility, created_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_servers_owner
                ON servers (owner_username)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS server_roles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    permissions TEXT NOT NULL,
                    is_default BOOLEAN DEFAULT 0,
                    sort_order INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                    UNIQUE (server_id, name)
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_server_roles_server
                ON server_roles (server_id, sort_order)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS server_memberships (
                    server_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    role_id INTEGER,
                    status TEXT DEFAULT 'pending',
                    invited_by TEXT,
                    invite_code TEXT,
                    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    joined_at DATETIME,
                    last_active_at DATETIME,
                    reviewed_at DATETIME,
                    reviewed_by TEXT,
                    PRIMARY KEY (server_id, username),
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                    FOREIGN KEY (role_id) REFERENCES server_roles (id) ON DELETE SET NULL,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_server_memberships_status
                ON server_memberships (server_id, status, requested_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS server_channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    channel_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    topic TEXT,
                    position INTEGER DEFAULT 0,
                    settings TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (server_id, slug),
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_server_channels_order
                ON server_channels (server_id, position ASC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS server_invites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    created_by TEXT,
                    code TEXT UNIQUE NOT NULL,
                    expires_at DATETIME,
                    max_uses INTEGER,
                    uses INTEGER DEFAULT 0,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                    FOREIGN KEY (created_by) REFERENCES users (username) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_server_invites_server
                ON server_invites (server_id, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    sender_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    rich_content TEXT,
                    message_type TEXT DEFAULT 'text',
                    thread_root_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    edited_at DATETIME,
                    deleted_at DATETIME,
                    FOREIGN KEY (channel_id) REFERENCES server_channels (id) ON DELETE CASCADE,
                    FOREIGN KEY (sender_id) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_channel_created
                ON messages (channel_id, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS message_reactions (
                    message_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    reaction_type TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (message_id, username, reaction_type),
                    FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_message_reactions_message
                ON message_reactions (message_id, reaction_type)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    storage_key TEXT NOT NULL,
                    type TEXT NOT NULL,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_attachments_message
                ON attachments (message_id, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS dm_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_type TEXT NOT NULL,
                    title TEXT,
                    created_by TEXT,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_message_at DATETIME,
                    FOREIGN KEY (created_by) REFERENCES users (username) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_dm_conversations_last_message
                ON dm_conversations (last_message_at DESC, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS dm_participants (
                    conversation_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    left_at DATETIME,
                    last_read_message_id INTEGER,
                    last_read_at DATETIME,
                    last_active_at DATETIME,
                    PRIMARY KEY (conversation_id, username),
                    FOREIGN KEY (conversation_id) REFERENCES dm_conversations (id) ON DELETE CASCADE,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_dm_participants_user
                ON dm_participants (username, conversation_id)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS dm_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    sender_id TEXT NOT NULL,
                    body TEXT,
                    rich_content TEXT,
                    message_type TEXT DEFAULT 'text',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    edited_at DATETIME,
                    deleted_at DATETIME,
                    FOREIGN KEY (conversation_id) REFERENCES dm_conversations (id) ON DELETE CASCADE,
                    FOREIGN KEY (sender_id) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_dm_messages_conversation_created
                ON dm_messages (conversation_id, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS dm_message_reactions (
                    message_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    reaction_type TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (message_id, username, reaction_type),
                    FOREIGN KEY (message_id) REFERENCES dm_messages (id) ON DELETE CASCADE,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_dm_reactions_message
                ON dm_message_reactions (message_id, reaction_type)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS feed_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    actor_username TEXT,
                    entity_type TEXT,
                    entity_id TEXT,
                    server_slug TEXT,
                    target_username TEXT,
                    audience_type TEXT DEFAULT 'global',
                    audience_id TEXT,
                    payload TEXT,
                    score REAL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_feed_events_audience
                ON feed_events (audience_type, audience_id, created_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_feed_events_created_at
                ON feed_events (created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS moderation_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    actor_username TEXT,
                    action_type TEXT NOT NULL,
                    target_id TEXT,
                    target_type TEXT,
                    reason TEXT,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                    FOREIGN KEY (actor_username) REFERENCES users (username) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_moderation_actions_server_created
                ON moderation_actions (server_id, created_at DESC)
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS moderation_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'warning',
                    message TEXT,
                    details TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    triggered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME,
                    resolved_by TEXT,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                    FOREIGN KEY (resolved_by) REFERENCES users (username) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_moderation_alerts_server_status
                ON moderation_alerts (server_id, status, triggered_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_username TEXT,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    context TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    resolved_at DATETIME,
                    FOREIGN KEY (reporter_username) REFERENCES users (username) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_reports_status_created
                ON reports (status, created_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_reports_target
                ON reports (target_type, target_id)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    event_id INTEGER,
                    notification_type TEXT NOT NULL,
                    payload TEXT,
                    delivery_status TEXT DEFAULT 'in_app',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    seen_at DATETIME,
                    read_at DATETIME,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (event_id) REFERENCES feed_events (id) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_notifications_user
                ON notifications (username, created_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_notifications_status
                ON notifications (delivery_status, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS server_owner_digests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    owner_username TEXT NOT NULL,
                    period_start DATETIME NOT NULL,
                    period_end DATETIME NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    delivery_channel TEXT DEFAULT 'email',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    delivered_at DATETIME,
                    failure_reason TEXT,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                    FOREIGN KEY (owner_username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_server_owner_digests_status
                ON server_owner_digests (status, created_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_server_owner_digests_server
                ON server_owner_digests (server_id, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS server_boost_tiers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    price_cents INTEGER NOT NULL DEFAULT 0,
                    currency TEXT NOT NULL DEFAULT 'usd',
                    benefits TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_server_boost_tiers_server
                ON server_boost_tiers (server_id, is_active, sort_order)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS server_boosts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    tier_id INTEGER NOT NULL,
                    purchaser_username TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                    FOREIGN KEY (tier_id) REFERENCES server_boost_tiers (id) ON DELETE CASCADE,
                    FOREIGN KEY (purchaser_username) REFERENCES users (username) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_server_boosts_server_status
                ON server_boosts (server_id, status, expires_at)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS referral_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_username TEXT NOT NULL,
                    code TEXT NOT NULL UNIQUE,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    max_uses INTEGER,
                    use_count INTEGER DEFAULT 0,
                    signup_count INTEGER DEFAULT 0,
                    FOREIGN KEY (owner_username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_referral_codes_owner
                ON referral_codes (owner_username, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS referral_hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referral_code_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    landing_page TEXT,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (referral_code_id) REFERENCES referral_codes (id) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_referral_hits_code_created
                ON referral_hits (code, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS referral_conversions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referral_code_id INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    referrer_username TEXT NOT NULL,
                    referred_username TEXT NOT NULL UNIQUE,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (referral_code_id) REFERENCES referral_codes (id) ON DELETE CASCADE,
                    FOREIGN KEY (referrer_username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (referred_username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_referral_conversions_referrer
                ON referral_conversions (referrer_username, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS server_tips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    cta_label TEXT,
                    cta_url TEXT,
                    audience TEXT DEFAULT 'all',
                    active INTEGER DEFAULT 1,
                    dismissible INTEGER DEFAULT 1,
                    priority INTEGER DEFAULT 0,
                    start_at DATETIME,
                    end_at DATETIME,
                    metadata TEXT,
                    created_by TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE CASCADE,
                    FOREIGN KEY (created_by) REFERENCES users (username) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_server_tips_active
                ON server_tips (server_id, active, priority DESC, created_at DESC)
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS server_tip_dismissals (
                    tip_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    dismissed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tip_id, username),
                    FOREIGN KEY (tip_id) REFERENCES server_tips (id) ON DELETE CASCADE,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS user_streaks (
                    username TEXT PRIMARY KEY,
                    current_streak INTEGER NOT NULL DEFAULT 0,
                    longest_streak INTEGER NOT NULL DEFAULT 0,
                    last_engaged_date DATE,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    server_id INTEGER,
                    reporter_username TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    severity TEXT NOT NULL DEFAULT 'medium',
                    assigned_to TEXT,
                    related_report_id INTEGER,
                    related_digest_id INTEGER,
                    first_response_at DATETIME,
                    resolved_at DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_activity_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (server_id) REFERENCES servers (id) ON DELETE SET NULL,
                    FOREIGN KEY (reporter_username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (assigned_to) REFERENCES users (username) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS support_ticket_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    actor_username TEXT,
                    event_type TEXT NOT NULL,
                    comment TEXT,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES support_tickets (id) ON DELETE CASCADE,
                    FOREIGN KEY (actor_username) REFERENCES users (username) ON DELETE SET NULL
                )
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_support_tickets_status
                ON support_tickets (status, severity, created_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_support_tickets_server
                ON support_tickets (server_id, status, created_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_support_tickets_assigned
                ON support_tickets (assigned_to, status, created_at DESC)
            """)

            c.execute("""
                CREATE INDEX IF NOT EXISTS idx_support_ticket_events_ticket
                ON support_ticket_events (ticket_id, created_at DESC)
            """)

            default_visibility_json = _dump_json(_profile_default_visibility())
            default_showcase_json = _dump_json(_profile_default_showcase())

            c.execute("""
                INSERT INTO profiles (username, display_name, visibility_settings, search_interests, showcase_config, created_at, updated_at)
                SELECT u.username, u.username, ?, '[]', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                FROM users u
                WHERE NOT EXISTS (
                    SELECT 1 FROM profiles p WHERE p.username = u.username
                )
            """, (default_visibility_json, default_showcase_json))

            # Listings table
            c.execute("""
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    price INTEGER,
                    link TEXT UNIQUE,
                    image_url TEXT,
                    source TEXT,
                    created_at DATETIME,
                    premium_placement INTEGER DEFAULT 0,
                    premium_until DATETIME,
                    user_id TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (username)
                )
            """)
            
            # Settings table - supports user-specific settings
            c.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    key TEXT,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, key),
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # User activity logging table
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    action TEXT,
                    details TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Rate limiting table
            c.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    endpoint TEXT,
                    request_count INTEGER DEFAULT 1,
                    window_start DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, endpoint)
                )
            """)
            
            # User scraper management table
            c.execute("""
                CREATE TABLE IF NOT EXISTS user_scrapers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    scraper_name TEXT,
                    is_running BOOLEAN DEFAULT 0,
                    last_run DATETIME,
                    run_count INTEGER DEFAULT 0,
                    UNIQUE(username, scraper_name),
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Analytics tables for market insights
            c.execute("""
                CREATE TABLE IF NOT EXISTS listing_analytics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER,
                    keyword TEXT,
                    category TEXT,
                    price_range TEXT,
                    source TEXT,
                    premium_impressions INTEGER DEFAULT 0,
                    premium_clicks INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (listing_id) REFERENCES listings (id) ON DELETE CASCADE
                )
            """)
            
            # Seller listings table - for items users want to sell
            c.execute("""
                CREATE TABLE IF NOT EXISTS seller_listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT,
                    price INTEGER NOT NULL,
                    original_cost INTEGER,
                    category TEXT,
                    location TEXT,
                    images TEXT,
                    marketplaces TEXT,
                    status TEXT DEFAULT 'draft',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    posted_at DATETIME,
                    sold_at DATETIME,
                    sold_on_marketplace TEXT,
                    actual_sale_price INTEGER,
                    craigslist_url TEXT,
                    facebook_url TEXT,
                    ksl_url TEXT,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Add new columns to existing tables if they don't exist
            try:
                c.execute("ALTER TABLE seller_listings ADD COLUMN sold_at DATETIME")
                logger.info("Added sold_at column to seller_listings table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE seller_listings ADD COLUMN sold_on_marketplace TEXT")
                logger.info("Added sold_on_marketplace column to seller_listings table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE seller_listings ADD COLUMN actual_sale_price INTEGER")
                logger.info("Added actual_sale_price column to seller_listings table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            try:
                c.execute("ALTER TABLE seller_listings ADD COLUMN original_cost INTEGER")
                logger.info("Added original_cost column to seller_listings table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            c.execute("""
                CREATE TABLE IF NOT EXISTS keyword_trends (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT,
                    count INTEGER,
                    avg_price REAL,
                    date DATE,
                    source TEXT,
                    user_id TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            c.execute("""
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id INTEGER,
                    price INTEGER,
                    recorded_at DATETIME,
                    FOREIGN KEY (listing_id) REFERENCES listings (id) ON DELETE CASCADE
                )
            """)
            
            c.execute("""
                CREATE TABLE IF NOT EXISTS market_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE,
                    total_listings INTEGER,
                    avg_price REAL,
                    min_price INTEGER,
                    max_price INTEGER,
                    source TEXT,
                    category TEXT
                )
            """)
            
            # Subscription tables
            c.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    tier TEXT DEFAULT 'free',
                    status TEXT DEFAULT 'active',
                    stripe_customer_id TEXT,
                    stripe_subscription_id TEXT,
                    current_period_start DATETIME,
                    current_period_end DATETIME,
                    cancel_at_period_end BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            c.execute("""
                CREATE TABLE IF NOT EXISTS subscription_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    action TEXT NOT NULL,
                    stripe_event_id TEXT,
                    details TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Email verification tokens
            c.execute("""
                CREATE TABLE IF NOT EXISTS email_verification_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    used BOOLEAN DEFAULT 0,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)

            try:
                c.execute("ALTER TABLE email_verification_tokens ADD COLUMN code_hash TEXT")
                logger.info("Added code_hash column to email_verification_tokens table")
            except Exception as e:
                if not _ignore_duplicate_schema_error(conn, e):
                    raise
            
            # Password reset tokens
            c.execute("""
                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME NOT NULL,
                    used BOOLEAN DEFAULT 0,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Security events table
            c.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address TEXT NOT NULL,
                    path TEXT NOT NULL,
                    user_agent TEXT,
                    reason TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Favorites/Bookmarks
            c.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    listing_id INTEGER NOT NULL,
                    notes TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(username, listing_id),
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE,
                    FOREIGN KEY (listing_id) REFERENCES listings (id) ON DELETE CASCADE
                )
            """)
            
            # Saved searches
            c.execute("""
                CREATE TABLE IF NOT EXISTS saved_searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    name TEXT NOT NULL,
                    keywords TEXT,
                    min_price INTEGER,
                    max_price INTEGER,
                    sources TEXT,
                    location TEXT,
                    radius INTEGER,
                    notify_new BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_run DATETIME,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Price alerts
            c.execute("""
                CREATE TABLE IF NOT EXISTS price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    threshold_price INTEGER NOT NULL,
                    alert_type TEXT DEFAULT 'under',
                    active BOOLEAN DEFAULT 1,
                    last_triggered DATETIME,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (username) REFERENCES users (username) ON DELETE CASCADE
                )
            """)
            
            # Add subscription columns to users if they don't exist (backward compatibility)
            try:
                c.execute("ALTER TABLE users ADD COLUMN subscription_tier TEXT DEFAULT 'free'")
                logger.info("Added subscription_tier column to users table")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Add user_id column to keyword_trends if it doesn't exist
            try:
                c.execute("ALTER TABLE keyword_trends ADD COLUMN user_id TEXT")
                logger.info("Added user_id column to keyword_trends table")
            except sqlite3.OperationalError:
                pass  # Column already exists
            
            # Create comprehensive indexes for performance
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_listings_created_at ON listings(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source)",
                "CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price)",
                "CREATE INDEX IF NOT EXISTS idx_listings_user_id ON listings(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
                "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
                "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
                "CREATE INDEX IF NOT EXISTS idx_activity_username ON user_activity(username)",
                "CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON user_activity(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_activity_action ON user_activity(action)",
                "CREATE INDEX IF NOT EXISTS idx_analytics_keyword ON listing_analytics(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_analytics_date ON listing_analytics(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_trends_date ON keyword_trends(date)",
                "CREATE INDEX IF NOT EXISTS idx_trends_keyword ON keyword_trends(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_trends_user_id ON keyword_trends(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_market_stats_date ON market_stats(date)",
                "CREATE INDEX IF NOT EXISTS idx_rate_limits_username ON rate_limits(username)",
                "CREATE INDEX IF NOT EXISTS idx_rate_limits_endpoint ON rate_limits(endpoint)",
                "CREATE INDEX IF NOT EXISTS idx_settings_username ON settings(username)",
                "CREATE INDEX IF NOT EXISTS idx_seller_listings_username ON seller_listings(username)",
                "CREATE INDEX IF NOT EXISTS idx_seller_listings_status ON seller_listings(status)",
                "CREATE INDEX IF NOT EXISTS idx_seller_listings_created ON seller_listings(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_username ON subscriptions(username)",
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_tier ON subscriptions(tier)",
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status)",
                "CREATE INDEX IF NOT EXISTS idx_subscriptions_customer_id ON subscriptions(stripe_customer_id)",
                "CREATE INDEX IF NOT EXISTS idx_subscription_history_username ON subscription_history(username)",
                "CREATE INDEX IF NOT EXISTS idx_email_verification_token ON email_verification_tokens(token)",
                "CREATE INDEX IF NOT EXISTS idx_email_verification_username ON email_verification_tokens(username)",
                "CREATE INDEX IF NOT EXISTS idx_password_reset_token ON password_reset_tokens(token)",
                "CREATE INDEX IF NOT EXISTS idx_password_reset_username ON password_reset_tokens(username)",
                "CREATE INDEX IF NOT EXISTS idx_favorites_username ON favorites(username)",
                "CREATE INDEX IF NOT EXISTS idx_favorites_listing ON favorites(listing_id)",
                "CREATE INDEX IF NOT EXISTS idx_saved_searches_username ON saved_searches(username)",
                "CREATE INDEX IF NOT EXISTS idx_price_alerts_username ON price_alerts(username)",
                "CREATE INDEX IF NOT EXISTS idx_price_alerts_active ON price_alerts(active)",
            ]
            
            for index_sql in indexes:
                c.execute(index_sql)

            conn.commit()
            logger.info("Database initialized successfully with all tables and indexes")
            return True
    except Exception as exc:
        logger.exception("Failed to initialize database schema: %s", exc)
        raise


@log_errors()
def log_profile_activity(username: str, activity_type: str, entity_id: Optional[str] = None,
                         metadata: Optional[Dict[str, Any]] = None, visibility: Optional[str] = None) -> None:
    if visibility not in {None, "public", "connections", "private"}:
        visibility = None

    payload = dict(metadata or {})
    if visibility:
        payload["visibility"] = visibility

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO profile_activity (username, activity_type, entity_id, metadata, occurred_at)
            VALUES (?, ?, ?, ?, ?)
        """, (username, activity_type, entity_id, _dump_json(payload), datetime.now()))
        conn.commit()

    try:
        record_user_engagement(username, f"profile_activity:{activity_type}")
    except Exception:
        pass


def _is_field_visible(visibility: Dict[str, str],
                      field: str,
                      viewer_username: Optional[str],
                      owner_username: str) -> bool:
    setting = (visibility or {}).get(field) or DEFAULT_PROFILE_VISIBILITY.get(field, "public")
    setting = str(setting).lower()

    if viewer_username == owner_username:
        return True

    if setting == "public":
        return True

    if setting == "private":
        return False

    if setting == "connections":
        if not viewer_username:
            return False
        try:
            if is_user_blocked(owner_username, viewer_username):
                return False
        except Exception:
            pass
        try:
            if are_friends(owner_username, viewer_username):
                return True
        except Exception:
            pass
        try:
            if is_profile_contact(owner_username, viewer_username):
                return True
        except Exception:
            pass
        # Fallback: treat authenticated viewers as connections.
        return True

    return True


def _get_profile_row(username: str) -> Optional[Tuple[Any, ...]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql("""
            SELECT id,
                   username,
                   display_name,
                   bio,
                   avatar_url,
                   banner_url,
                   gender,
                   pronouns,
                   location,
                   search_interests,
                   showcase_config,
                   visibility_settings,
                   created_at,
                   updated_at
            FROM profiles
            WHERE username = ?
        """), (username,))
        return c.fetchone()


@log_errors()
def ensure_profile(username: str) -> Dict[str, Any]:
    if not username:
        raise ValueError("username is required")

    visibility_json = _dump_json(_profile_default_visibility())
    showcase_json = _dump_json(_profile_default_showcase())
    now = datetime.now()

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql("""
            INSERT INTO profiles (
                username,
                display_name,
                search_interests,
                showcase_config,
                visibility_settings,
                created_at,
                updated_at
            )
            SELECT ?, ?, '[]', ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM profiles WHERE username = ?
            )
        """), (
            username,
            username,
            showcase_json,
            visibility_json,
            now,
            now,
            username,
        ))
        conn.commit()

    row = _get_profile_row(username)
    return _profile_row_to_dict(row)


@log_errors()
def get_profile(username: str) -> Dict[str, Any]:
    if not username:
        return {}
    row = _get_profile_row(username)
    if not row:
        return ensure_profile(username)
    return _profile_row_to_dict(row)


@log_errors()
def update_profile(username: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    if not username:
        raise ValueError("username is required")
    ensure_profile(username)

    if not updates:
        return get_profile(username)

    allowed_fields = {
        "display_name",
        "bio",
        "avatar_url",
        "banner_url",
        "gender",
        "pronouns",
        "location",
        "search_interests",
    }

    set_clauses: List[str] = []
    params: List[Any] = []

    for key, value in updates.items():
        if key not in allowed_fields:
            continue

        if key == "search_interests":
            sanitized = _sanitize_search_interests(value)
            set_clauses.append("search_interests = ?")
            params.append(_dump_json(sanitized))
            continue

        if value is None:
            normalized = None
        else:
            normalized = str(value).strip()
            if not normalized:
                normalized = None

        if key == "display_name" and not normalized:
            normalized = username

        set_clauses.append(f"{key} = ?")
        params.append(normalized)

    if not set_clauses:
        return get_profile(username)

    params.extend([datetime.now(), username])

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql(f"""
            UPDATE profiles
            SET {", ".join(set_clauses)}, updated_at = ?
            WHERE username = ?
        """), params)
        conn.commit()

    return get_profile(username)


@log_errors()
def update_profile_visibility(username: str, visibility_updates: Dict[str, Any]) -> Dict[str, Any]:
    if not username:
        raise ValueError("username is required")
    if not visibility_updates:
        profile = get_profile(username)
        return profile.get("visibility_settings", _profile_default_visibility())

    profile = ensure_profile(username)
    visibility = _merge_visibility_defaults(profile.get("visibility_settings"))

    changed = False
    for key, value in (visibility_updates or {}).items():
        if key not in visibility:
            continue
        option = str(value).lower()
        if option in {"public", "connections", "private"} and visibility.get(key) != option:
            visibility[key] = option
            changed = True

    if not changed:
        return get_profile(username)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql("""
            UPDATE profiles
            SET visibility_settings = ?, updated_at = ?
            WHERE username = ?
        """), (_dump_json(visibility), datetime.now(), username))
        conn.commit()

    return visibility


@log_errors()
def get_profile_for_viewer(username: str, viewer_username: Optional[str]) -> Dict[str, Any]:
    profile = ensure_profile(username)
    visibility = profile.get("visibility_settings", _profile_default_visibility())

    visible_profile = deepcopy(profile)

    for field in PROFILE_FIELD_KEYS:
        if not _is_field_visible(visibility, field, viewer_username, username):
            if field == "search_interests":
                visible_profile[field] = []
            else:
                visible_profile[field] = None

    if not _is_field_visible(visibility, "showcase", viewer_username, username):
        visible_profile["showcase_config"] = _profile_default_showcase()

    return visible_profile


@log_errors()
def get_profile_activity(username: str, limit: int = 10, viewer_username: Optional[str] = None) -> List[Dict[str, Any]]:
    profile = ensure_profile(username)
    visibility = profile.get("visibility_settings", _profile_default_visibility())
    if not _is_field_visible(visibility, "recent_activity", viewer_username, username):
        return []

    results: List[Dict[str, Any]] = []
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT activity_type, entity_id, metadata, occurred_at
            FROM profile_activity
            WHERE username = ?
            ORDER BY occurred_at DESC
            LIMIT ?
        """, (username, limit))
        rows = c.fetchall()

    for row in rows:
        metadata = _load_json(row[2], {})
        entry_visibility = metadata.get("visibility")
        if viewer_username != username:
            if entry_visibility == "private":
                continue
            if entry_visibility == "connections" and viewer_username is None:
                continue

        results.append({
            "activity_type": row[0],
            "entity_id": row[1],
            "metadata": metadata,
            "occurred_at": _to_datetime_string(row[3]),
        })
    return results


# ======================
# PROFILE CONTACTS
# ======================


@log_errors()
def get_profile_contact(owner_username: str, contact_username: str) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT owner_username, contact_username, created_at
            FROM profile_contacts
            WHERE owner_username = ?
              AND contact_username = ?
        """, (owner_username, contact_username))
        row = c.fetchone()

    if not row:
        return None

    return {
        "owner_username": row[0],
        "contact_username": row[1],
        "created_at": _to_datetime_string(row[2]),
    }


@log_errors()
def list_profile_contacts(owner_username: str, limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 500))
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT contact_username, created_at
            FROM profile_contacts
            WHERE owner_username = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (owner_username, limit))
        rows = c.fetchall()

    contacts: List[Dict[str, Any]] = []
    for row in rows:
        contacts.append({
            "owner_username": owner_username,
            "contact_username": row[0],
            "created_at": _to_datetime_string(row[1]),
        })
    return contacts


@log_errors()
def is_profile_contact(owner_username: str, contact_username: str) -> bool:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 1
            FROM profile_contacts
            WHERE owner_username = ?
              AND contact_username = ?
        """, (owner_username, contact_username))
        row = c.fetchone()
    return bool(row)


@log_errors()
def add_profile_contact(owner_username: str, contact_username: str) -> Tuple[Dict[str, Any], bool]:
    if not owner_username or not contact_username:
        raise ValueError("Both usernames are required.")
    if owner_username == contact_username:
        raise ValueError("You cannot add yourself as a contact.")

    now = datetime.now()
    created = False

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        try:
            c.execute("""
                INSERT INTO profile_contacts (owner_username, contact_username, created_at)
                VALUES (?, ?, ?)
            """, (owner_username, contact_username, now))
            conn.commit()
            created = True
        except Exception as e:
            message = str(e).lower()
            duplicate_tokens = {"unique", "duplicate", "constraint failed", "primary key"}
            if any(token in message for token in duplicate_tokens):
                try:
                    conn.rollback()
                except Exception:
                    pass
            else:
                if USE_POSTGRES:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                raise

    contact = get_profile_contact(owner_username, contact_username)
    if contact is None:
        contact = {
            "owner_username": owner_username,
            "contact_username": contact_username,
            "created_at": _to_datetime_string(now),
        }

    if created:
        try:
            log_profile_activity(
                owner_username,
                "profile_contact_added",
                entity_id=contact_username,
                metadata={"contact": contact_username},
                visibility="connections",
            )
        except Exception:
            pass

    return contact, created


@log_errors()
def _sanitize_friend_request_message(message: Optional[str]) -> Optional[str]:
    if message is None:
        return None
    text = str(message).strip()
    if not text:
        return None
    if len(text) > FRIEND_REQUEST_MESSAGE_MAX_LENGTH:
        text = text[:FRIEND_REQUEST_MESSAGE_MAX_LENGTH]
    return text
def _insert_friendship_row(conn, owner_username: str, friend_username: str, created_at: datetime, source_request_id: Optional[int]):
    statement = """
        INSERT OR IGNORE INTO friendships (owner_username, friend_username, created_at, source_request_id)
        VALUES (?, ?, ?, ?)
    """
    if USE_POSTGRES:
        statement = """
            INSERT INTO friendships (owner_username, friend_username, created_at, source_request_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (owner_username, friend_username) DO NOTHING
        """
    cursor = conn.cursor()
    cursor.execute(statement, (owner_username, friend_username, created_at, source_request_id))


def _friend_request_row_to_dict(
    row,
    direction: str,
    include_user: bool = True,
    *,
    mutual_friend_count: int = 0,
    mutual_friend_preview: Optional[List[Dict[str, Any]]] = None,
    mutual_server_count: int = 0,
    mutual_server_preview: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    request = {
        "id": row[0],
        "requester_username": row[1],
        "recipient_username": row[2],
        "status": row[3],
        "message": row[4],
        "created_at": _to_datetime_string(row[5]),
        "responded_at": _to_datetime_string(row[6]),
        "direction": direction,
    }
    if include_user and len(row) >= 10:
        request["other_user"] = {
            "username": row[7],
            "display_name": row[8],
            "avatar_url": row[9],
        }
    request["mutual_friend_count"] = int(mutual_friend_count or 0)
    request["mutual_friend_preview"] = mutual_friend_preview or []
    request["mutual_server_count"] = int(mutual_server_count or 0)
    request["mutual_server_preview"] = mutual_server_preview or []
    return request


def _friendship_row_to_dict(
    row,
    *,
    mutual_friend_count: int = 0,
    mutual_friend_preview: Optional[List[Dict[str, Any]]] = None,
    mutual_server_count: int = 0,
    mutual_server_preview: Optional[List[Dict[str, Any]]] = None,
    last_active_at: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "username": row[0],
        "display_name": row[3],
        "avatar_url": row[4],
        "created_at": _to_datetime_string(row[1]),
        "source_request_id": row[2],
        "mutual_friend_count": int(mutual_friend_count or 0),
        "mutual_friend_preview": mutual_friend_preview or [],
        "mutual_server_count": int(mutual_server_count or 0),
        "mutual_server_preview": mutual_server_preview or [],
        "last_active_at": last_active_at,
    }


def _fetch_friend_usernames(cursor, username: str) -> Set[str]:
    cursor.execute("""
        SELECT friend_username
        FROM friendships
        WHERE owner_username = ?
    """, (username,))
    return {row[0] for row in cursor.fetchall()}


def _collect_mutual_friend_data(
    cursor,
    owner_username: str,
    friend_usernames: Sequence[str],
    preview_limit: int = 3,
) -> Tuple[Dict[str, int], Dict[str, List[Dict[str, Any]]]]:
    friend_usernames = [username for username in friend_usernames if username]
    if not friend_usernames:
        return {}, {}

    owner_friend_set = _fetch_friend_usernames(cursor, owner_username)
    owner_friend_set.discard(owner_username)
    if not owner_friend_set:
        return {}, {}

    mutual_map: Dict[str, List[str]] = {}
    all_preview_usernames: Set[str] = set()

    for friend_username in friend_usernames:
        if friend_username == owner_username:
            continue
        cursor.execute("""
            SELECT friend_username
            FROM friendships
            WHERE owner_username = ?
        """, (friend_username,))
        friend_set = {row[0] for row in cursor.fetchall()}
        mutual_candidates = sorted(
            (owner_friend_set & friend_set) - {owner_username, friend_username}
        )
        if mutual_candidates:
            mutual_map[friend_username] = mutual_candidates
            all_preview_usernames.update(mutual_candidates[:preview_limit])

    if not mutual_map:
        return {}, {}

    preview_profile_map: Dict[str, Dict[str, Any]] = {}
    if all_preview_usernames:
        placeholders = ",".join("?" for _ in all_preview_usernames)
        cursor.execute(f"""
            SELECT username, display_name, COALESCE(avatar_url, '')
            FROM profiles
            WHERE username IN ({placeholders})
        """, tuple(all_preview_usernames))
        preview_profile_map = {
            row[0]: {
                "username": row[0],
                "display_name": row[1] or row[0],
                "avatar_url": row[2],
            }
            for row in cursor.fetchall()
        }

    counts: Dict[str, int] = {}
    previews: Dict[str, List[Dict[str, Any]]] = {}
    for friend_username, usernames in mutual_map.items():
        counts[friend_username] = len(usernames)
        preview: List[Dict[str, Any]] = []
        for mutual_username in usernames:
            if len(preview) >= preview_limit:
                break
            preview.append(
                preview_profile_map.get(
                    mutual_username,
                    {
                        "username": mutual_username,
                        "display_name": mutual_username,
                        "avatar_url": "",
                    },
                )
            )
        previews[friend_username] = preview
    return counts, previews


def _fetch_user_active_servers_map(cursor, username: str) -> Dict[int, Dict[str, Any]]:
    cursor.execute("""
        SELECT sm.server_id, s.slug, s.name
        FROM server_memberships sm
        JOIN servers s ON s.id = sm.server_id
        WHERE sm.username = ?
          AND sm.status = 'active'
    """, (username,))
    return {
        row[0]: {
            "slug": row[1],
            "name": row[2],
        }
        for row in cursor.fetchall()
    }


def _collect_mutual_server_data(
    cursor,
    owner_username: str,
    friend_usernames: Sequence[str],
    owner_server_map: Dict[int, Dict[str, Any]],
    preview_limit: int = 3,
) -> Tuple[Dict[str, int], Dict[str, List[Dict[str, Any]]]]:
    friend_usernames = [username for username in friend_usernames if username]
    if not friend_usernames or not owner_server_map:
        return {}, {}

    counts: Dict[str, int] = {}
    previews: Dict[str, List[Dict[str, Any]]] = {}

    owner_server_ids = set(owner_server_map.keys())

    for friend_username in friend_usernames:
        if friend_username == owner_username:
            continue
        cursor.execute("""
            SELECT server_id
            FROM server_memberships
            WHERE username = ?
              AND status = 'active'
        """, (friend_username,))
        friend_server_ids = {row[0] for row in cursor.fetchall()}
        mutual_ids = sorted(owner_server_ids & friend_server_ids)
        if mutual_ids:
            counts[friend_username] = len(mutual_ids)
            sample: List[Dict[str, Any]] = []
            for server_id in mutual_ids:
                info = owner_server_map.get(server_id)
                if info:
                    sample.append(info)
                if len(sample) >= preview_limit:
                    break
            previews[friend_username] = sample

    return counts, previews


def _fetch_last_active_map(cursor, usernames: Sequence[str]) -> Dict[str, Optional[str]]:
    usernames = [name for name in usernames if name]
    if not usernames:
        return {}

    placeholders = ",".join("?" for _ in usernames)
    cursor.execute(f"""
        SELECT username,
               MAX(COALESCE(last_active_at, joined_at)) AS last_active
        FROM server_memberships
        WHERE username IN ({placeholders})
        GROUP BY username
    """, tuple(usernames))
    last_active_map: Dict[str, Optional[str]] = {
        row[0]: _to_datetime_string(row[1]) for row in cursor.fetchall() if row[1]
    }

    missing = [username for username in usernames if username not in last_active_map]
    if missing:
        placeholders_missing = ",".join("?" for _ in missing)
        cursor.execute(f"""
            SELECT username, updated_at
            FROM profiles
            WHERE username IN ({placeholders_missing})
        """, tuple(missing))
        for row in cursor.fetchall():
            last_active_map[row[0]] = _to_datetime_string(row[1])

    return last_active_map


def _extract_interest_slugs_from_profile(profile: Optional[Dict[str, Any]]) -> Set[str]:
    if not profile:
        return set()
    interest_slugs: Set[str] = set()
    for item in profile.get("search_interests") or []:
        if isinstance(item, dict):
            label = item.get("slug") or item.get("label") or item.get("id")
        else:
            label = str(item)
        if not label:
            continue
        slug = _slugify(label, fallback="")
        if slug:
            interest_slugs.add(slug)
    return interest_slugs


def _get_viewer_server_memberships(cursor, viewer_username: str) -> List[Dict[str, Any]]:
    cursor.execute("""
        SELECT
            s.id,
            s.name,
            s.slug,
            s.topic_tags,
            sm.joined_at
        FROM server_memberships sm
        JOIN servers s ON s.id = sm.server_id
        WHERE sm.username = ?
          AND sm.status = 'active'
    """, (viewer_username,))
    rows = cursor.fetchall()
    memberships: List[Dict[str, Any]] = []
    for row in rows:
        memberships.append({
            "id": row[0],
            "name": row[1],
            "slug": row[2],
            "topic_tags": _load_json(row[3], []),
            "joined_at": _to_datetime_string(row[4]),
        })
    return memberships


def _enrich_servers_for_viewer(
    cursor,
    viewer_username: str,
    servers: List[Dict[str, Any]],
    *,
    interest_slugs: Optional[Set[str]] = None,
    viewer_memberships: Optional[List[Dict[str, Any]]] = None,
) -> None:
    if not servers:
        return

    server_ids = [server.get("id") for server in servers if server.get("id")]
    server_ids = [sid for sid in server_ids if isinstance(sid, int)]
    if not server_ids:
        return

    now = datetime.now()
    interest_slugs = set(interest_slugs or [])
    if not interest_slugs:
        profile = get_profile(viewer_username)
        interest_slugs = _extract_interest_slugs_from_profile(profile)

    viewer_memberships = viewer_memberships or _get_viewer_server_memberships(cursor, viewer_username)

    viewer_server_tag_map: Dict[int, Set[str]] = {}
    for membership in viewer_memberships:
        tags = set()
        for tag in membership.get("topic_tags") or []:
            slug = None
            if isinstance(tag, dict):
                slug = tag.get("slug") or tag.get("label") or tag.get("id")
            else:
                slug = str(tag)
            slug = _slugify(slug, fallback="") if slug else ""
            if slug:
                tags.add(slug)
        if tags:
            viewer_server_tag_map[membership.get("id")] = tags

    friend_members_map: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    friend_set = _fetch_friend_usernames(cursor, viewer_username)
    friend_set.discard(viewer_username)
    unique_friend_usernames = tuple(sorted(friend_set))
    unique_server_ids = tuple(sorted(set(server_ids)))

    if unique_friend_usernames and unique_server_ids:
        placeholders_servers = ",".join("?" for _ in unique_server_ids)
        placeholders_friends = ",".join("?" for _ in unique_friend_usernames)
        params = unique_server_ids + unique_friend_usernames
        cursor.execute(
            f"""
            SELECT sm.server_id,
                   sm.username,
                   COALESCE(p.display_name, sm.username),
                   COALESCE(p.avatar_url, '')
            FROM server_memberships sm
            JOIN profiles p ON p.username = sm.username
            WHERE sm.server_id IN ({placeholders_servers})
              AND sm.status = 'active'
              AND sm.username IN ({placeholders_friends})
            ORDER BY sm.server_id, p.display_name ASC, sm.username ASC
            """,
            params,
        )
        for row in cursor.fetchall():
            if row[1] == viewer_username:
                continue
            friend_members_map[row[0]].append({
                "username": row[1],
                "display_name": row[2] or row[1],
                "avatar_url": row[3],
            })

    interest_slugs = interest_slugs or set()
    viewer_membership_list = viewer_memberships or []

    for server in servers:
        server_id = server.get("id")
        if not isinstance(server_id, int):
            continue

        topic_tags = server.get("topic_tags") or []
        topic_slug_map: Dict[str, str] = {}
        for tag in topic_tags:
            if isinstance(tag, dict):
                label = tag.get("label") or tag.get("slug") or tag.get("id")
                slug = tag.get("slug") or _slugify(label, fallback="")
            else:
                label = str(tag)
                slug = _slugify(label, fallback="")
            if slug:
                topic_slug_map[slug] = label or slug

        interest_matches = [topic_slug_map[slug] for slug in topic_slug_map.keys() if slug in interest_slugs]

        friend_preview_full = friend_members_map.get(server_id, [])
        friend_preview = friend_preview_full[:3]
        friend_preview_remaining = max(len(friend_preview_full) - len(friend_preview), 0)

        related_servers: List[Dict[str, Any]] = []
        for membership in viewer_membership_list:
            membership_tags = viewer_server_tag_map.get(membership.get("id"), set())
            overlap = sorted(set(topic_slug_map.keys()) & membership_tags)
            if overlap:
                related_servers.append({
                    "slug": membership.get("slug"),
                    "name": membership.get("name"),
                    "overlap_tags": [topic_slug_map.get(tag, tag) for tag in overlap],
                })
            if len(related_servers) >= 3:
                break

        created_at_dt = _parse_db_datetime(server.get("created_at"))
        age_days: Optional[float] = None
        if created_at_dt:
            age_days = max((now - created_at_dt).total_seconds() / 86400.0, 0.0)

        base_score = float(server.get("personalized_score") or server.get("discovery_score") or server.get("score") or 0.0)
        score = base_score
        if friend_preview_full:
            score += len(friend_preview_full) * 4.0
        if interest_matches:
            score += len(interest_matches) * 2.0
        if age_days is not None:
            if age_days < 30.0:
                score += max(0.0, 6.0 - age_days * 0.2)

        personalization = server.get("personalization") or {}
        personalization.update({
            "friend_member_count": len(friend_preview_full),
            "friend_member_preview": friend_preview,
            "friend_member_preview_remaining": friend_preview_remaining,
            "interest_overlap": len(interest_matches),
            "interest_match_tags": interest_matches,
            "related_servers": related_servers,
            "score_breakdown": {
                "base": round(base_score, 3),
                "friends": len(friend_preview_full) * 4.0,
                "interests": len(interest_matches) * 2.0,
                "recency": round(score - base_score - len(friend_preview_full) * 4.0 - len(interest_matches) * 2.0, 3),
            },
        })
        reasons: List[str] = []
        if friend_preview_full:
            reasons.append(f"{len(friend_preview_full)} friend{'s' if len(friend_preview_full) != 1 else ''} already joined")
        if interest_matches:
            reasons.append(f"Matches your interests ({', '.join(interest_matches[:3])})")
        if related_servers:
            reasons.append("Similar to servers you already follow")
        personalization["reasons"] = reasons

        server["personalization"] = personalization
        server["personalized_score"] = round(score, 3)


@log_errors()
def get_pending_friend_request_between(user_a: str, user_b: str) -> Optional[Dict[str, Any]]:
    if not user_a or not user_b:
        return None
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, requester_username, recipient_username, status, message, created_at, responded_at
            FROM friend_requests
            WHERE status = ?
              AND (
                (requester_username = ? AND recipient_username = ?)
                OR
                (requester_username = ? AND recipient_username = ?)
              )
            ORDER BY created_at DESC
            LIMIT 1
        """, (
            FRIEND_REQUEST_STATUS_PENDING,
            user_a,
            user_b,
            user_b,
            user_a,
        ))
        row = c.fetchone()

    if not row:
        return None

    direction = "outgoing" if row[1] == user_a else "incoming"
    return _friend_request_row_to_dict(row, direction, include_user=False)


@log_errors()
def are_friends(user_a: str, user_b: str) -> bool:
    if not user_a or not user_b:
        return False
    if user_a == user_b:
        return True
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 1
            FROM friendships
            WHERE owner_username = ?
              AND friend_username = ?
        """, (user_a, user_b))
        return bool(c.fetchone())


@log_errors()
def list_friendships(username: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT f.friend_username,
                   f.created_at,
                   f.source_request_id,
                   p.display_name,
                   COALESCE(p.avatar_url, '')
            FROM friendships AS f
            LEFT JOIN profiles AS p
              ON p.username = f.friend_username
            WHERE f.owner_username = ?
            ORDER BY f.created_at DESC, f.friend_username ASC
            LIMIT ? OFFSET ?
        """, (username, limit, offset))
        rows = c.fetchall()
        friend_usernames = [row[0] for row in rows]
        mutual_friend_counts, mutual_friend_previews = _collect_mutual_friend_data(c, username, friend_usernames)
        owner_server_map = _fetch_user_active_servers_map(c, username)
        mutual_server_counts, mutual_server_previews = _collect_mutual_server_data(
            c,
            username,
            friend_usernames,
            owner_server_map,
        )
        last_active_map = _fetch_last_active_map(c, friend_usernames)

    return [
        _friendship_row_to_dict(
            row,
            mutual_friend_count=mutual_friend_counts.get(row[0], 0),
            mutual_friend_preview=mutual_friend_previews.get(row[0], []),
            mutual_server_count=mutual_server_counts.get(row[0], 0),
            mutual_server_preview=mutual_server_previews.get(row[0], []),
            last_active_at=last_active_map.get(row[0]),
        )
        for row in rows
    ]


@log_errors()
def count_friendships(username: str) -> int:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*)
            FROM friendships
            WHERE owner_username = ?
        """, (username,))
        row = c.fetchone()
    return int(row[0]) if row else 0


@log_errors()
def count_pending_friend_requests(username: str, direction: str = "incoming") -> int:
    direction = "incoming" if direction != "outgoing" else "outgoing"
    column = "recipient_username" if direction == "incoming" else "requester_username"
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT COUNT(*)
            FROM friend_requests
            WHERE {column} = ?
              AND status = ?
        """, (username, FRIEND_REQUEST_STATUS_PENDING))
        row = c.fetchone()
    return int(row[0]) if row else 0


@log_errors()
def is_user_blocked(owner_username: str, blocked_username: str) -> bool:
    if not owner_username or not blocked_username:
        return False
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 1
            FROM user_blocks
            WHERE owner_username = ? AND blocked_username = ?
            LIMIT 1
        """, (owner_username, blocked_username))
        return bool(c.fetchone())


def _are_users_blocked(cursor, user_a: str, user_b: str) -> bool:
    if not user_a or not user_b:
        return False
    cursor.execute("""
        SELECT 1
        FROM user_blocks
        WHERE (owner_username = ? AND blocked_username = ?)
           OR (owner_username = ? AND blocked_username = ?)
        LIMIT 1
    """, (user_a, user_b, user_b, user_a))
    return bool(cursor.fetchone())
def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value))
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
    return None


def _increment_friend_request_quota(username: str) -> None:
    if FRIEND_REQUEST_THROTTLE_LIMIT <= 0:
        return
    now = datetime.now()
    window_threshold = now - timedelta(hours=FRIEND_REQUEST_THROTTLE_WINDOW_HOURS)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT window_start, request_count
            FROM friend_request_throttle
            WHERE username = ?
        """, (username,))
        row = c.fetchone()

        if row:
            window_start = _parse_datetime(row[0]) or window_threshold
            request_count = int(row[1] or 0)
            if window_start <= window_threshold:
                window_start = now
                request_count = 0
            if request_count >= FRIEND_REQUEST_THROTTLE_LIMIT:
                raise ValueError("Friend request limit reached. Try again later.")
            request_count += 1
            c.execute("""
                UPDATE friend_request_throttle
                SET window_start = ?, request_count = ?
                WHERE username = ?
            """, (_to_datetime_string(window_start), request_count, username))
        else:
            c.execute("""
                INSERT INTO friend_request_throttle (username, window_start, request_count)
                VALUES (?, ?, ?)
            """, (username, _to_datetime_string(now), 1))
        conn.commit()


@log_errors()
def list_user_blocks(owner_username: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    if not owner_username:
        return {"blocks": [], "total": 0, "limit": limit, "offset": offset}
    bounded_limit = max(1, min(int(limit), USER_BLOCK_MAX_TARGETS))
    bounded_offset = max(0, int(offset))

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*)
            FROM user_blocks
            WHERE owner_username = ?
        """, (owner_username,))
        total_row = c.fetchone()
        total = int(total_row[0]) if total_row else 0

        c.execute("""
            SELECT ub.blocked_username,
                   ub.reason,
                   ub.created_at,
                   COALESCE(p.display_name, ub.blocked_username) AS display_name,
                   p.avatar_url
            FROM user_blocks ub
            LEFT JOIN profiles p ON p.username = ub.blocked_username
            WHERE ub.owner_username = ?
            ORDER BY ub.created_at DESC, ub.blocked_username ASC
            LIMIT ? OFFSET ?
        """, (owner_username, bounded_limit, bounded_offset))
        rows = c.fetchall()

    blocks: List[Dict[str, Any]] = []
    for row in rows:
        blocks.append({
            "blocked_username": row[0],
            "display_name": row[3],
            "avatar_url": row[4],
            "reason": row[1],
            "created_at": _to_datetime_string(row[2]),
        })

    return {
        "blocks": blocks,
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
    }


@log_errors()
def block_user(owner_username: str, blocked_username: str, reason: Optional[str] = None) -> Dict[str, Any]:
    if not owner_username or not blocked_username:
        raise ValueError("Both usernames are required.")
    if owner_username == blocked_username:
        raise ValueError("You cannot block yourself.")
    if not get_user_by_username(blocked_username):
        raise ValueError("User not found.")

    now = datetime.now()

    with get_pool().get_connection() as conn:
        c = conn.cursor()

        if _are_users_blocked(c, owner_username, blocked_username):
            c.execute("""
                SELECT reason, created_at
                FROM user_blocks
                WHERE owner_username = ? AND blocked_username = ?
            """, (owner_username, blocked_username))
            row = c.fetchone()
            created_at = row[1] if row else now
            return {
                "blocked_username": blocked_username,
                "reason": row[0] if row else reason,
                "created_at": _to_datetime_string(created_at),
            }

        c.execute("""
            SELECT COUNT(*)
            FROM user_blocks
            WHERE owner_username = ?
        """, (owner_username,))
        count_row = c.fetchone()
        if count_row and int(count_row[0]) >= USER_BLOCK_MAX_TARGETS:
            raise ValueError("Block list is full.")

        c.execute("""
            DELETE FROM friend_requests
            WHERE (requester_username = ? AND recipient_username = ?)
               OR (requester_username = ? AND recipient_username = ?)
        """, (owner_username, blocked_username, blocked_username, owner_username))

        c.execute("""
            INSERT INTO user_blocks (owner_username, blocked_username, reason, created_at)
            VALUES (?, ?, ?, ?)
        """, (owner_username, blocked_username, reason, now))

        conn.commit()

    remove_friendship(owner_username, blocked_username)

    try:
        log_profile_activity(
            owner_username,
            "user_blocked",
            entity_id=blocked_username,
            metadata={"reason": reason} if reason else {},
            visibility="private",
        )
    except Exception:
        pass

    return {
        "blocked_username": blocked_username,
        "reason": reason,
        "created_at": _to_datetime_string(now),
    }


@log_errors()
def unblock_user(owner_username: str, blocked_username: str) -> bool:
    if not owner_username or not blocked_username:
        return False
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM user_blocks
            WHERE owner_username = ? AND blocked_username = ?
        """, (owner_username, blocked_username))
        removed = c.rowcount
        conn.commit()

    if removed:
        try:
            log_profile_activity(
                owner_username,
                "user_unblocked",
                entity_id=blocked_username,
                metadata={},
                visibility="private",
            )
        except Exception:
            pass
    return bool(removed)
@log_errors()
def create_friend_request(requester_username: str, recipient_username: str, message: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
    if not requester_username or not recipient_username:
        raise ValueError("Both requester and recipient are required.")
    if requester_username == recipient_username:
        raise ValueError("You cannot send a friend request to yourself.")

    recipient_exists = get_user_by_username(recipient_username)
    if not recipient_exists:
        raise ValueError("Recipient not found.")

    if are_friends(requester_username, recipient_username):
        raise ValueError("You are already friends.")

    existing = get_pending_friend_request_between(requester_username, recipient_username)
    if existing:
        return existing, False

    if is_user_blocked(requester_username, recipient_username):
        raise ValueError("You have blocked this user.")
    if is_user_blocked(recipient_username, requester_username):
        raise ValueError("This user has blocked you.")

    _increment_friend_request_quota(requester_username)

    sanitized_message = _sanitize_friend_request_message(message)
    now = datetime.now()

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        try:
            if USE_POSTGRES:
                c.execute("""
                    INSERT INTO friend_requests (
                        requester_username,
                        recipient_username,
                        status,
                        message,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    RETURNING id
                """, (
                    requester_username,
                    recipient_username,
                    FRIEND_REQUEST_STATUS_PENDING,
                    sanitized_message,
                    now,
                ))
                request_id_row = c.fetchone()
                request_id = request_id_row[0] if request_id_row else None
                conn.commit()
            else:
                c.execute("""
                    INSERT INTO friend_requests (
                        requester_username,
                        recipient_username,
                        status,
                        message,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    requester_username,
                    recipient_username,
                    FRIEND_REQUEST_STATUS_PENDING,
                    sanitized_message,
                    now,
                ))
                request_id = c.lastrowid
                conn.commit()
        except Exception as exc:
            duplicate = False
            if isinstance(exc, sqlite3.IntegrityError):
                duplicate = True
            elif USE_POSTGRES and getattr(exc, "pgcode", None) == "23505":
                duplicate = True
            if duplicate:
                try:
                    conn.rollback()
                except Exception:
                    pass
                existing = get_pending_friend_request_between(requester_username, recipient_username)
                if existing:
                    return existing, False
            raise

    request = {
        "id": request_id,
        "requester_username": requester_username,
        "recipient_username": recipient_username,
        "status": FRIEND_REQUEST_STATUS_PENDING,
        "message": sanitized_message,
        "created_at": _to_datetime_string(now),
        "responded_at": None,
        "direction": "outgoing",
    }

    log_profile_activity(
        requester_username,
        "friend_request_sent",
        entity_id=recipient_username,
        metadata={"target": recipient_username},
        visibility="connections",
    )

    return request, True


@log_errors()
def list_friend_requests(username: str, direction: str = "incoming", status: str = FRIEND_REQUEST_STATUS_PENDING, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    direction = "incoming" if direction != "outgoing" else "outgoing"
    if status not in FRIEND_REQUEST_STATUSES:
        status = FRIEND_REQUEST_STATUS_PENDING
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    column = "recipient_username" if direction == "incoming" else "requester_username"
    join_column = "requester_username" if direction == "incoming" else "recipient_username"

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT fr.id,
                   fr.requester_username,
                   fr.recipient_username,
                   fr.status,
                   fr.message,
                   fr.created_at,
                   fr.responded_at,
                   fr.{join_column} AS other_username,
                   COALESCE(p.display_name, ''),
                   COALESCE(p.avatar_url, '')
            FROM friend_requests AS fr
            LEFT JOIN profiles AS p
              ON p.username = fr.{join_column}
            WHERE fr.{column} = ?
              AND fr.status = ?
            ORDER BY fr.created_at DESC, fr.id DESC
            LIMIT ? OFFSET ?
        """, (username, status, limit, offset))
        rows = c.fetchall()

        other_usernames = [row[7] for row in rows]
        mutual_friend_counts, mutual_friend_previews = _collect_mutual_friend_data(c, username, other_usernames)
        owner_server_map = _fetch_user_active_servers_map(c, username)
        mutual_server_counts, mutual_server_previews = _collect_mutual_server_data(
            c,
            username,
            other_usernames,
            owner_server_map,
        )

    return [
        _friend_request_row_to_dict(
            row,
            direction,
            mutual_friend_count=mutual_friend_counts.get(row[7], 0),
            mutual_friend_preview=mutual_friend_previews.get(row[7], []),
            mutual_server_count=mutual_server_counts.get(row[7], 0),
            mutual_server_preview=mutual_server_previews.get(row[7], []),
        )
        for row in rows
    ]


@log_errors()
def cancel_friend_request(request_id: int, requester_username: str) -> bool:
    if not requester_username or not request_id:
        return False

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT requester_username, status
            FROM friend_requests
            WHERE id = ?
        """, (request_id,))
        row = c.fetchone()
        if not row or row[0] != requester_username or row[1] != FRIEND_REQUEST_STATUS_PENDING:
            return False

        now = datetime.now()
        c.execute("""
            UPDATE friend_requests
            SET status = ?, responded_at = ?
            WHERE id = ?
        """, (FRIEND_REQUEST_STATUS_CANCELLED, now, request_id))
        conn.commit()

    log_profile_activity(
        requester_username,
        "friend_request_cancelled",
        entity_id=str(request_id),
        metadata={"request_id": request_id},
        visibility="private",
    )
    return True


@log_errors()
def respond_friend_request(request_id: int, recipient_username: str, action: str) -> Dict[str, Any]:
    action_normalized = action.lower().strip() if action else ""
    if action_normalized not in {"accept", "decline"}:
        raise ValueError("Invalid action. Expected 'accept' or 'decline'.")

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id,
                   requester_username,
                   recipient_username,
                   status,
                   message,
                   created_at,
                   responded_at
            FROM friend_requests
            WHERE id = ?
        """, (request_id,))
        row = c.fetchone()
        if not row:
            raise ValueError("Friend request not found.")
        if row[2] != recipient_username:
            raise ValueError("You are not authorized to respond to this request.")
        if row[3] != FRIEND_REQUEST_STATUS_PENDING:
            return _friend_request_row_to_dict(row, "incoming", include_user=False)

        now = datetime.now()
        new_status = FRIEND_REQUEST_STATUS_ACCEPTED if action_normalized == "accept" else FRIEND_REQUEST_STATUS_DECLINED
        c.execute("""
            UPDATE friend_requests
            SET status = ?, responded_at = ?
            WHERE id = ?
        """, (new_status, now, request_id))

        if action_normalized == "accept":
            _insert_friendship_row(conn, row[1], row[2], now, row[0])
            _insert_friendship_row(conn, row[2], row[1], now, row[0])

        conn.commit()

    if action_normalized == "accept":
        log_profile_activity(
            row[1],
            "friend_request_accepted",
            entity_id=row[2],
            metadata={"request_id": request_id},
            visibility="connections",
        )
        log_profile_activity(
            row[2],
            "friend_added",
            entity_id=row[1],
            metadata={"request_id": request_id},
            visibility="connections",
        )
    else:
        log_profile_activity(
            row[2],
            "friend_request_declined",
            entity_id=row[1],
            metadata={"request_id": request_id},
            visibility="private",
        )

    updated = {
        "id": row[0],
        "requester_username": row[1],
        "recipient_username": row[2],
        "status": new_status,
        "message": row[4],
        "created_at": _to_datetime_string(row[5]),
        "responded_at": _to_datetime_string(now),
        "direction": "incoming",
    }
    return updated
@log_errors()
def remove_friendship(owner_username: str, friend_username: str) -> bool:
    if not owner_username or not friend_username:
        return False

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM friendships
            WHERE (owner_username = ? AND friend_username = ?)
               OR (owner_username = ? AND friend_username = ?)
        """, (owner_username, friend_username, friend_username, owner_username))
        removed = c.rowcount
        conn.commit()

    if removed:
        log_profile_activity(
            owner_username,
            "friend_removed",
            entity_id=friend_username,
            metadata={},
            visibility="connections",
        )
        log_profile_activity(
            friend_username,
            "friend_removed",
            entity_id=owner_username,
            metadata={},
            visibility="connections",
        )
    return bool(removed)


@log_errors()
def get_friend_relationship(viewer_username: Optional[str], target_username: str) -> Dict[str, Any]:
    if not viewer_username:
        return {"status": "unauthenticated"}
    if viewer_username == target_username:
        return {"status": "self"}
    if not get_user_by_username(target_username):
        return {"status": "not_found"}

    if is_user_blocked(viewer_username, target_username):
        return {"status": "blocked_by_viewer"}
    if is_user_blocked(target_username, viewer_username):
        return {"status": "blocked_viewer"}

    if are_friends(viewer_username, target_username):
        return {"status": "friends"}

    pending = get_pending_friend_request_between(viewer_username, target_username)
    if pending:
        status = "outgoing_pending" if pending["requester_username"] == viewer_username else "incoming_pending"
        pending["status"] = FRIEND_REQUEST_STATUS_PENDING
        return {"status": status, "request": pending}

    return {"status": "none"}


@log_errors()
def get_friend_overview(username: str, limit: int = 20) -> Dict[str, Any]:
    limit = max(5, min(limit, 100))
    friends = list_friendships(username, limit=limit)
    incoming = list_friend_requests(username, direction="incoming", status=FRIEND_REQUEST_STATUS_PENDING, limit=limit)
    outgoing = list_friend_requests(username, direction="outgoing", status=FRIEND_REQUEST_STATUS_PENDING, limit=limit)
    total_friends = count_friendships(username)
    next_cursor = None
    if len(friends) == limit and total_friends > limit:
        next_cursor = limit

    summary = {
        "friends": friends,
        "incoming_requests": incoming,
        "outgoing_requests": outgoing,
        "incoming": incoming,
        "outgoing": outgoing,
        "counts": {
            "friends": total_friends,
            "incoming": count_pending_friend_requests(username, direction="incoming"),
            "outgoing": count_pending_friend_requests(username, direction="outgoing"),
        },
        "next_cursor": next_cursor,
        "is_complete": next_cursor is None,
    }
    return summary


@log_errors()
def is_profile_field_visible(username: str, field: str, viewer_username: Optional[str]) -> bool:
    profile = ensure_profile(username)
    visibility = profile.get("visibility_settings", _profile_default_visibility())
    return _is_field_visible(visibility, field, viewer_username, username)


def _sanitize_showcase_item(item: Dict[str, Any], position: int) -> Optional[Dict[str, Any]]:
    entity_id = item.get("entity_id")
    if entity_id in (None, ""):
        return None

    label = item.get("label")
    if label is not None:
        label = str(label).strip() or None

    metadata = dict(item.get("metadata") or {})
    note = item.get("note")
    if note is not None:
        metadata["note"] = str(note)[:80]
    elif "note" in metadata and metadata["note"] is not None:
        metadata["note"] = str(metadata["note"])[:80]

    return {
        "entity_id": str(entity_id),
        "label": label,
        "position": position,
        "metadata": metadata,
    }


@log_errors()
def set_profile_showcase(username: str, collection_type: str, items: List[Dict[str, Any]]) -> Dict[str, List[int]]:
    if collection_type not in PROFILE_COLLECTION_TYPES:
        raise ValueError(f"Unsupported showcase collection: {collection_type}")

    ensure_profile(username)
    normalized_items = []
    for idx, raw_item in enumerate(items[:10]):
        normalized = _sanitize_showcase_item(raw_item, idx)
        if normalized:
            normalized_items.append(normalized)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM profile_showcase_items
            WHERE username = ? AND collection_type = ?
        """, (username, collection_type))

        now = datetime.now()
        for item in normalized_items:
            c.execute("""
                INSERT INTO profile_showcase_items (
                    username,
                    collection_type,
                    entity_id,
                    label,
                    position,
                    metadata,
                    added_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                username,
                collection_type,
                item["entity_id"],
                item["label"],
                item["position"],
                _dump_json(item["metadata"]),
                now,
                now,
            ))

        c.execute("""
            SELECT showcase_config
            FROM profiles
            WHERE username = ?
        """, (username,))
        row = c.fetchone()
        current_config = _load_json(row[0], _profile_default_showcase()) if row else _profile_default_showcase()

        c.execute("""
            SELECT id
            FROM profile_showcase_items
            WHERE username = ? AND collection_type = ?
            ORDER BY position ASC, id ASC
        """, (username, collection_type))
        item_ids = [r[0] for r in c.fetchall()]
        current_config[collection_type] = item_ids

        c.execute("""
            UPDATE profiles
            SET showcase_config = ?, updated_at = ?
            WHERE username = ?
        """, (_dump_json(current_config), now, username))

        conn.commit()

    log_profile_activity(
        username,
        "showcase_updated",
        entity_id=collection_type,
        metadata={"count": len(normalized_items)},
        visibility="connections",
    )

    return get_profile(username)["showcase_config"]


@log_errors()
def get_profile_showcase(username: str) -> Dict[str, List[Dict[str, Any]]]:
    ensure_profile(username)
    collections: Dict[str, List[Dict[str, Any]]] = {key: [] for key in PROFILE_COLLECTION_TYPES}

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, collection_type, entity_id, label, position, metadata, added_at, updated_at
            FROM profile_showcase_items
            WHERE username = ?
            ORDER BY collection_type ASC, position ASC, id ASC
        """, (username,))
        rows = c.fetchall()

    for row in rows:
        collection = row[1]
        if collection not in collections:
            collections[collection] = []
        collections[collection].append({
            "id": row[0],
            "entity_id": row[2],
            "label": row[3],
            "position": row[4],
            "metadata": _load_json(row[5], {}),
            "added_at": _to_datetime_string(row[6]),
            "updated_at": _to_datetime_string(row[7]),
        })

    return collections


# ======================
# COMMUNITY SERVERS
# ======================


def _bootstrap_server_roles(cursor, server_id: int, timestamp: datetime) -> Dict[str, int]:
    role_ids: Dict[str, int] = {}
    for blueprint in DEFAULT_SERVER_ROLE_BLUEPRINT:
        cursor.execute("""
            INSERT INTO server_roles (server_id, name, permissions, is_default, sort_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            server_id,
            blueprint["name"],
            _dump_json(blueprint["permissions"]),
            bool(blueprint.get("is_default")),
            blueprint.get("sort_order", 0),
            timestamp,
        ))
        role_ids[blueprint["key"]] = cursor.lastrowid
    return role_ids


def _bootstrap_server_channels(cursor, server_id: int, timestamp: datetime) -> None:
    for blueprint in DEFAULT_SERVER_CHANNEL_BLUEPRINT:
        cursor.execute("""
            INSERT INTO server_channels (server_id, channel_type, name, slug, topic, position, settings, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            server_id,
            blueprint["type"],
            blueprint["name"],
            blueprint["slug"],
            blueprint.get("topic"),
            blueprint.get("position", 0),
            _dump_json(blueprint.get("settings", {})),
            timestamp,
            timestamp,
        ))


def _generate_channel_slug(cursor, server_id: int, base_name: str) -> str:
    base = _slugify(base_name, fallback="channel")
    slug_candidate = base
    suffix = 2
    while True:
        cursor.execute("""
            SELECT 1
            FROM server_channels
            WHERE server_id = ? AND slug = ?
        """, (server_id, slug_candidate))
        if not cursor.fetchone():
            return slug_candidate
        slug_candidate = f"{base}-{suffix}"
        suffix += 1


def _get_default_role_id(cursor, server_id: int) -> Optional[int]:
    cursor.execute("""
        SELECT id
        FROM server_roles
        WHERE server_id = ? AND is_default = 1
        ORDER BY sort_order ASC, id ASC
        LIMIT 1
    """, (server_id,))
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("""
        SELECT id
        FROM server_roles
        WHERE server_id = ?
        ORDER BY sort_order ASC, id ASC
        LIMIT 1
    """, (server_id,))
    row = cursor.fetchone()
    return row[0] if row else None
def _channel_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    settings = _load_json(row[7], {})
    return {
        "id": row[0],
        "server_id": row[1],
        "type": row[2],
        "name": row[3],
        "slug": row[4],
        "topic": row[5],
        "position": row[6],
        "settings": settings if isinstance(settings, dict) else {},
        "created_at": _to_datetime_string(row[8]),
        "updated_at": _to_datetime_string(row[9]),
    }


@log_errors()
def get_server_channel(channel_id: int) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, server_id, channel_type, name, slug, topic, position, settings, created_at, updated_at
            FROM server_channels
            WHERE id = ?
        """, (channel_id,))
        row = c.fetchone()
    if not row:
        return None
    return _channel_row_to_dict(row)


def _get_server_channels_with_cursor(cursor, server_id: int) -> List[Dict[str, Any]]:
    cursor.execute("""
        SELECT id, server_id, channel_type, name, slug, topic, position, settings, created_at, updated_at
        FROM server_channels
        WHERE server_id = ?
        ORDER BY position ASC, id ASC
    """, (server_id,))
    rows = cursor.fetchall()
    return [_channel_row_to_dict(row) for row in rows]


def _get_server_roles_with_cursor(cursor, server_id: int) -> List[Dict[str, Any]]:
    cursor.execute("""
        SELECT id, name, permissions, is_default, sort_order, created_at
        FROM server_roles
        WHERE server_id = ?
        ORDER BY sort_order ASC, id ASC
    """, (server_id,))
    roles: List[Dict[str, Any]] = []
    for row in cursor.fetchall():
        permissions = _load_json(row[2], {})
        roles.append({
            "id": row[0],
            "name": row[1],
            "permissions": permissions if isinstance(permissions, dict) else {},
            "is_default": bool(row[3]),
            "sort_order": row[4],
            "created_at": _to_datetime_string(row[5]),
        })
    return roles


def _get_membership_with_cursor(cursor, server_id: int, username: Optional[str], include_permissions: bool = False) -> Optional[Dict[str, Any]]:
    if not username:
        return None

    if include_permissions:
        cursor.execute("""
            SELECT m.server_id, m.username, m.role_id, m.status, m.invited_by, m.invite_code,
                   m.requested_at, m.joined_at, m.last_active_at, m.reviewed_at, m.reviewed_by,
                   r.name, r.permissions
            FROM server_memberships m
            LEFT JOIN server_roles r ON r.id = m.role_id
            WHERE m.server_id = ? AND m.username = ?
        """, (server_id, username))
    else:
        cursor.execute("""
            SELECT m.server_id, m.username, m.role_id, m.status, m.invited_by, m.invite_code,
                   m.requested_at, m.joined_at, m.last_active_at, m.reviewed_at, m.reviewed_by
            FROM server_memberships m
            WHERE m.server_id = ? AND m.username = ?
        """, (server_id, username))

    row = cursor.fetchone()
    if not row:
        return None
    return _serialize_membership_row(row)


def _get_server_member_counts(cursor, server_id: int) -> Tuple[int, int]:
    cursor.execute("""
        SELECT status, COUNT(*)
        FROM server_memberships
        WHERE server_id = ?
        GROUP BY status
    """, (server_id,))
    active = 0
    pending = 0
    for status, count in cursor.fetchall():
        if status == "active":
            active = count
        elif status == "pending":
            pending = count
    return active, pending


def _get_server_channel_count(cursor, server_id: int) -> int:
    cursor.execute("""
        SELECT COUNT(*)
        FROM server_channels
        WHERE server_id = ?
    """, (server_id,))
    row = cursor.fetchone()
    return row[0] if row else 0


def _compose_server_payload(cursor, server_row: Tuple[Any, ...], viewer_username: Optional[str],
                            include_channels: bool, include_roles: bool) -> Dict[str, Any]:
    server = _server_row_to_dict(server_row)
    active_count, pending_count = _get_server_member_counts(cursor, server["id"])
    server["member_count"] = active_count
    server["pending_requests"] = pending_count
    server["channel_count"] = _get_server_channel_count(cursor, server["id"])

    if include_channels:
        server["channels"] = _get_server_channels_with_cursor(cursor, server["id"])
    if include_roles:
        server["roles"] = _get_server_roles_with_cursor(cursor, server["id"])
    if viewer_username:
        server["viewer_membership"] = _get_membership_with_cursor(cursor, server["id"], viewer_username, include_permissions=True)
    return server


@log_errors()
def get_server_channel_by_slug(server_id: int, channel_slug: str) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, server_id, channel_type, name, slug, topic, position, settings, created_at, updated_at
            FROM server_channels
            WHERE server_id = ? AND slug = ?
        """, (server_id, channel_slug))
        row = c.fetchone()
    if not row:
        return None
    return _channel_row_to_dict(row)


def _fetch_channel_message_attachments(message_ids: Sequence[int]) -> Dict[int, List[Dict[str, Any]]]:
    if not message_ids:
        return {}

    placeholders = ",".join("?" for _ in message_ids)
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT id, message_id, storage_key, type, metadata, created_at
            FROM attachments
            WHERE message_id IN ({placeholders})
            ORDER BY created_at ASC, id ASC
        """, tuple(message_ids))
        rows = c.fetchall()

    attachment_map: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        metadata = _load_json(row[4], {})
        attachment_map.setdefault(row[1], []).append({
            "id": row[0],
            "storage_key": row[2],
            "type": row[3],
            "metadata": metadata if isinstance(metadata, dict) else {},
            "created_at": _to_datetime_string(row[5]),
        })
    return attachment_map
def _fetch_channel_message_reaction_map(message_ids: Sequence[int], viewer_username: Optional[str]) -> Dict[int, List[Dict[str, Any]]]:
    if not message_ids:
        return {}

    placeholders = ",".join("?" for _ in message_ids)
    if viewer_username:
        params: List[Any] = [viewer_username, *message_ids]
        query = f"""
            SELECT message_id,
                   reaction_type,
                   COUNT(*) AS total_count,
                   SUM(CASE WHEN username = ? THEN 1 ELSE 0 END) AS viewer_count
            FROM message_reactions
            WHERE message_id IN ({placeholders})
            GROUP BY message_id, reaction_type
        """
    else:
        params = list(message_ids)
        query = f"""
            SELECT message_id,
                   reaction_type,
                   COUNT(*) AS total_count,
                   0 AS viewer_count
            FROM message_reactions
            WHERE message_id IN ({placeholders})
            GROUP BY message_id, reaction_type
        """

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(query, tuple(params))
        rows = c.fetchall()

    reaction_map: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        reaction_map.setdefault(row[0], []).append({
            "reaction": row[1],
            "count": row[2],
            "viewer_reacted": bool(row[3]),
        })
    return reaction_map


@log_errors()
def get_channel_message(message_id: int, viewer_username: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT m.id,
                   m.channel_id,
                   m.sender_id,
                   COALESCE(m.body, '') AS body,
                   COALESCE(m.message_type, 'text') AS message_type,
                   m.rich_content,
                   m.thread_root_id,
                   m.created_at,
                   m.edited_at,
                   COALESCE(p.display_name, m.sender_id) AS display_name
            FROM messages m
            LEFT JOIN profiles p ON p.username = m.sender_id
            WHERE m.id = ?
              AND m.deleted_at IS NULL
        """, (message_id,))
        row = c.fetchone()

    if not row:
        return None

    attachments_map = _fetch_channel_message_attachments([message_id])
    reaction_map = _fetch_channel_message_reaction_map([message_id], viewer_username)
    rich_payload = _load_json(row[5], {})

    return {
        "id": row[0],
        "channel_id": row[1],
        "sender_id": row[2],
        "body": row[3],
        "message_type": row[4],
        "rich_content": rich_payload if isinstance(rich_payload, dict) else {},
        "thread_root_id": row[6],
        "created_at": _to_datetime_string(row[7]),
        "edited_at": _to_datetime_string(row[8]),
        "display_name": row[9],
        "attachments": attachments_map.get(row[0], []),
        "reactions": reaction_map.get(row[0], []),
    }


@log_errors()
def get_channel_messages(channel_id: int, limit: int = 50, after_id: Optional[int] = None,
                         viewer_username: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 200))
    base_query = """
        SELECT m.id,
               m.channel_id,
               m.sender_id,
               COALESCE(m.body, '') AS body,
               COALESCE(m.message_type, 'text') AS message_type,
               m.rich_content,
               m.thread_root_id,
               m.created_at,
               m.edited_at,
               COALESCE(p.display_name, m.sender_id) AS display_name
        FROM messages m
        LEFT JOIN profiles p ON p.username = m.sender_id
        WHERE m.channel_id = ?
          AND m.deleted_at IS NULL
    """
    params: List[Any] = [channel_id]
    if after_id is not None:
        base_query += " AND m.id > ?"
        params.append(after_id)

    base_query += " ORDER BY m.id ASC LIMIT ?" if after_id is not None else " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(base_query, tuple(params))
        rows = c.fetchall()

    if after_id is None:
        rows = list(reversed(rows))

    message_ids = [row[0] for row in rows]
    attachments_map = _fetch_channel_message_attachments(message_ids)
    reaction_map = _fetch_channel_message_reaction_map(message_ids, viewer_username)

    messages: List[Dict[str, Any]] = []
    for row in rows:
        rich_payload = _load_json(row[5], {})
        messages.append({
            "id": row[0],
            "channel_id": row[1],
            "sender_id": row[2],
            "body": row[3],
            "message_type": row[4],
            "rich_content": rich_payload if isinstance(rich_payload, dict) else {},
            "thread_root_id": row[6],
            "created_at": _to_datetime_string(row[7]),
            "edited_at": _to_datetime_string(row[8]),
            "display_name": row[9],
            "attachments": attachments_map.get(row[0], []),
            "reactions": reaction_map.get(row[0], []),
        })
    return messages


@log_errors()
def get_channel_message_attachments(message_id: int) -> List[Dict[str, Any]]:
    attachment_map = _fetch_channel_message_attachments([message_id])
    return attachment_map.get(message_id, [])


@log_errors()
def get_channel_message_reactions(message_id: int, viewer_username: Optional[str] = None) -> List[Dict[str, Any]]:
    reaction_map = _fetch_channel_message_reaction_map([message_id], viewer_username)
    return reaction_map.get(message_id, [])


@log_errors()
def add_channel_message_reaction(message_id: int, username: str, reaction_type: str) -> List[Dict[str, Any]]:
    reaction = (reaction_type or "").strip()
    if not reaction:
        raise ValueError("Reaction type is required")
    if len(reaction) > 32:
        raise ValueError("Reaction must be 32 characters or fewer")

    now = datetime.now()
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT OR IGNORE INTO message_reactions (message_id, username, reaction_type, created_at)
            VALUES (?, ?, ?, ?)
        """, (message_id, username, reaction, now))
        conn.commit()

    return get_channel_message_reactions(message_id, username)


@log_errors()
def remove_channel_message_reaction(message_id: int, username: str, reaction_type: str) -> List[Dict[str, Any]]:
    reaction = (reaction_type or "").strip()
    if not reaction:
        raise ValueError("Reaction type is required")

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM message_reactions
            WHERE message_id = ?
              AND username = ?
              AND reaction_type = ?
        """, (message_id, username, reaction))
        conn.commit()

    return get_channel_message_reactions(message_id, username)
@log_errors()
def create_channel_message(channel_id: int, sender_id: str, body: str,
                            message_type: str = "text", rich_content: Optional[Dict[str, Any]] = None,
                            attachments: Optional[Sequence[Dict[str, Any]]] = None,
                            thread_root_id: Optional[int] = None) -> Dict[str, Any]:
    clean_body = (body or "").strip()
    if len(clean_body) > 2000:
        raise ValueError("Message must be 2000 characters or fewer")

    normalized_type = (message_type or "text").strip().lower()
    allowed_types = {"text", "announcement", "listing", "link", "image", "attachment"}
    if normalized_type not in allowed_types:
        raise ValueError("Unsupported message type")

    normalized_thread_id: Optional[int] = None
    if thread_root_id is not None:
        try:
            normalized_thread_id = int(thread_root_id)
        except (TypeError, ValueError):
            raise ValueError("thread_root_id must be an integer")
        if normalized_thread_id <= 0:
            raise ValueError("thread_root_id must be positive")

    normalized_attachments: List[Dict[str, Any]] = []
    if attachments:
        for idx, item in enumerate(attachments):
            if not isinstance(item, dict):
                raise ValueError(f"Attachment #{idx + 1} must be an object")
            storage_key = (item.get("storage_key") or "").strip()
            attachment_type = (item.get("type") or "").strip().lower()
            if not storage_key:
                raise ValueError(f"Attachment #{idx + 1} is missing storage_key")
            if attachment_type not in {"image", "listing", "link"}:
                raise ValueError(f"Attachment #{idx + 1} has unsupported type")
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            normalized_attachments.append({
                "storage_key": storage_key,
                "type": attachment_type,
                "metadata": metadata,
            })

    if normalized_type == "text" and not clean_body:
        raise ValueError("Message cannot be empty")

    if not clean_body and not normalized_attachments and not rich_content:
        raise ValueError("Message content cannot be empty")

    now = datetime.now()
    rich_payload = _dump_json(rich_content) if rich_content else None

    channel_meta: Optional[Dict[str, Any]] = None
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT sc.server_id,
                   sc.channel_type,
                   sc.name,
                   sc.slug,
                   sc.settings,
                   s.slug AS server_slug,
                   s.name AS server_name
            FROM server_channels sc
            JOIN servers s ON s.id = sc.server_id
            WHERE sc.id = ?
        """, (channel_id,))
        channel_row = c.fetchone()
        if not channel_row:
            raise ValueError("Channel not found")
        channel_settings = _load_json(channel_row[4], {})
        channel_meta = {
            "server_id": channel_row[0],
            "channel_type": (channel_row[1] or "").lower(),
            "channel_name": channel_row[2],
            "channel_slug": channel_row[3],
            "settings": channel_settings if isinstance(channel_settings, dict) else {},
            "server_slug": channel_row[5],
            "server_name": channel_row[6],
        }

        c.execute("""
            INSERT INTO messages (channel_id, sender_id, body, rich_content, message_type, thread_root_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (channel_id, sender_id, clean_body, rich_payload, normalized_type, normalized_thread_id, now))
        message_id = c.lastrowid

        for attachment in normalized_attachments:
            c.execute("""
                INSERT INTO attachments (message_id, storage_key, type, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                message_id,
                attachment["storage_key"],
                attachment["type"],
                _dump_json(attachment["metadata"]),
                now,
            ))

        conn.commit()

    try:
        log_profile_activity(
            sender_id,
            "community_message_posted",
            entity_id=str(channel_id),
            metadata={
                "channel_id": channel_id,
                "message_id": message_id,
                "message_type": normalized_type,
                "attachment_count": len(normalized_attachments),
            },
            visibility="connections",
        )
    except Exception:
        pass

    message_record = get_channel_message(message_id, viewer_username=sender_id)
    if not message_record:
        message_record = {
            "id": message_id,
            "channel_id": channel_id,
            "sender_id": sender_id,
            "body": clean_body,
            "message_type": normalized_type,
            "rich_content": rich_content or {},
            "thread_root_id": normalized_thread_id,
            "created_at": _to_datetime_string(now),
            "edited_at": None,
            "display_name": sender_id,
            "attachments": normalized_attachments,
            "reactions": [],
        }

    if channel_meta:
        try:
            channel_type = channel_meta.get("channel_type") or ""
            snippet_source = (message_record.get("body") or "").strip()
            if not snippet_source and isinstance(rich_content, dict):
                snippet_source = str(
                    rich_content.get("title")
                    or rich_content.get("summary")
                    or rich_content.get("description")
                    or ""
                ).strip()
            if not snippet_source and normalized_type != "text":
                snippet_source = normalized_type.replace("_", " ").title()

            snippet = snippet_source
            if len(snippet) > 160:
                snippet = snippet[:157] + "…"

            payload: Dict[str, Any] = {
                "channel": {
                    "name": channel_meta.get("channel_name"),
                    "slug": channel_meta.get("channel_slug"),
                    "type": channel_type,
                },
                "server": {
                    "slug": channel_meta.get("server_slug"),
                    "name": channel_meta.get("server_name"),
                },
                "message": {
                    "id": message_record.get("id"),
                    "snippet": snippet,
                    "created_at": message_record.get("created_at"),
                    "type": normalized_type,
                    "sender": sender_id,
                },
            }
            if rich_content:
                payload["message"]["rich_content"] = rich_content

            event_type: Optional[str] = None
            event_score = 0.0
            if channel_type == "announcement":
                event_type = "server_announcement"
                event_score = 8.0
            elif channel_type == "marketplace" or message_type == "listing":
                event_type = "server_marketplace_drop"
                event_score = 5.0
            elif channel_type == "text" and len(snippet_source) >= 180:
                event_type = "server_hot_thread"
                event_score = 3.5

            server_slug = channel_meta.get("server_slug")
            if event_type and server_slug:
                log_feed_event(
                    event_type=event_type,
                    actor_username=sender_id,
                    entity_type="server_message",
                    entity_id=str(message_record.get("id")),
                    server_slug=server_slug,
                    audience_type="server",
                    audience_id=server_slug,
                    payload=payload,
                    score=event_score,
                )
                if event_type == "server_announcement":
                    log_feed_event(
                        event_type="home_server_highlight",
                        actor_username=sender_id,
                        entity_type="server_message",
                        entity_id=str(message_record.get("id")),
                        server_slug=server_slug,
                        audience_type="global",
                        payload=payload,
                        score=max(event_score - 1.0, 1.0),
                    )
        except Exception as exc:
            logger.warning(f"Failed to log server feed event for channel {channel_id}: {exc}")

    return message_record


@log_errors()
def log_moderation_action(server_id: int,
                           actor_username: Optional[str],
                           action_type: str,
                           *,
                           target_id: Optional[str] = None,
                           target_type: Optional[str] = None,
                           reason: Optional[str] = None,
                           metadata: Optional[Dict[str, Any]] = None,
                           created_at: Optional[datetime] = None) -> Dict[str, Any]:
    action = (action_type or "").strip()
    if not action:
        raise ValueError("action_type is required")

    timestamp = created_at or datetime.now()
    payload = metadata if isinstance(metadata, dict) else {}

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO moderation_actions (
                server_id,
                actor_username,
                action_type,
                target_id,
                target_type,
                reason,
                metadata,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            server_id,
            actor_username,
            action,
            target_id,
            target_type,
            reason,
            _dump_json(payload),
            timestamp,
        ))
        action_id = c.lastrowid
        conn.commit()

    return {
        "id": action_id,
        "server_id": server_id,
        "actor_username": actor_username,
        "action_type": action,
        "target_id": target_id,
        "target_type": target_type,
        "reason": reason,
        "metadata": payload,
        "created_at": _to_datetime_string(timestamp),
    }


@log_errors()
def list_moderation_actions(server_id: int,
                             limit: int = 50,
                             offset: int = 0,
                             action_types: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    bounded_limit = max(1, min(int(limit), 200))
    bounded_offset = max(0, int(offset))

    normalized_types: List[str] = []
    if action_types:
        for value in action_types:
            normalized = (value or "").strip().lower()
            if normalized and normalized not in normalized_types:
                normalized_types.append(normalized)

    base_where = "WHERE server_id = ?"
    base_params: List[Any] = [server_id]
    if normalized_types:
        placeholders = ", ".join("?" * len(normalized_types))
        base_where += f" AND LOWER(action_type) IN ({placeholders})"
        base_params.extend(normalized_types)

    count_sql = f"SELECT COUNT(*) FROM moderation_actions {base_where}"
    query_sql = f"""
        SELECT id,
               server_id,
               actor_username,
               action_type,
               target_id,
               target_type,
               reason,
               metadata,
               created_at
        FROM moderation_actions
        {base_where}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
    """

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql(count_sql), base_params)
        count_row = c.fetchone()
        total = count_row[0] if count_row else 0

        c.execute(
            _prepare_sql(query_sql),
            base_params + [bounded_limit, bounded_offset],
        )
        rows = c.fetchall()

    actions: List[Dict[str, Any]] = []
    for row in rows:
        metadata = _load_json(row[7], {})
        actions.append({
            "id": row[0],
            "server_id": row[1],
            "actor_username": row[2],
            "action_type": row[3],
            "target_id": row[4],
            "target_type": row[5],
            "reason": row[6],
            "metadata": metadata if isinstance(metadata, dict) else {},
            "created_at": _to_datetime_string(row[8]),
        })

    return {
        "actions": actions,
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
    }


@log_errors()
def get_moderation_actions_export(
    server_id: int,
    *,
    start: Optional[Any] = None,
    end: Optional[Any] = None,
    action_types: Optional[Sequence[str]] = None,
    limit: int = 5000,
) -> Dict[str, Any]:
    """
    Return moderation actions for export/audit purposes.
    Supports optional start/end datetime filters and action_type filtering.
    """
    bounded_limit = max(1, min(int(limit), 50000))

    start_dt = _parse_db_datetime(start) if start else None
    end_dt = _parse_db_datetime(end) if end else None
    normalized_types: List[str] = []
    if action_types:
        for value in action_types:
            normalized = (value or "").strip().lower()
            if normalized and normalized not in normalized_types:
                normalized_types.append(normalized)

    where_clauses = ["server_id = ?"]
    params: List[Any] = [server_id]

    if normalized_types:
        placeholders = ", ".join("?" * len(normalized_types))
        where_clauses.append(f"LOWER(action_type) IN ({placeholders})")
        params.extend(normalized_types)

    if start_dt:
        where_clauses.append("created_at >= ?")
        params.append(start_dt)
    if end_dt:
        where_clauses.append("created_at <= ?")
        params.append(end_dt)

    where_sql = " AND ".join(where_clauses)
    query_sql = f"""
        SELECT id,
               server_id,
               actor_username,
               action_type,
               target_id,
               target_type,
               reason,
               metadata,
               created_at
        FROM moderation_actions
        WHERE {where_sql}
        ORDER BY created_at DESC, id DESC
        LIMIT ?
    """

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql(query_sql), params + [bounded_limit])
        rows = c.fetchall()

    actions: List[Dict[str, Any]] = []
    for row in rows:
        metadata = _load_json(row[7], {})
        actions.append({
            "id": row[0],
            "server_id": row[1],
            "actor_username": row[2],
            "action_type": row[3],
            "target_id": row[4],
            "target_type": row[5],
            "reason": row[6],
            "metadata": metadata if isinstance(metadata, dict) else {},
            "created_at": _to_datetime_string(row[8]),
        })

    return {
        "actions": actions,
        "count": len(actions),
        "filters": {
            "start": _to_datetime_string(start_dt) if start_dt else None,
            "end": _to_datetime_string(end_dt) if end_dt else None,
            "action_types": normalized_types,
            "limit": bounded_limit,
        },
        "exported_at": _to_datetime_string(datetime.now()),
    }


def _generate_referral_code(length: int = REFERRAL_CODE_LENGTH) -> str:
    return "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(length))


def _normalize_referral_code(value: str) -> str:
    return (value or "").strip().upper()


def _referral_code_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {
        "id": row[0],
        "owner_username": row[1],
        "code": row[2],
        "metadata": _load_json(row[3], {}),
        "created_at": _to_datetime_string(row[4]),
        "expires_at": _to_datetime_string(row[5]),
        "max_uses": row[6],
        "use_count": row[7] or 0,
        "signup_count": row[8] or 0,
    }


@log_errors()
def get_referral_code(owner_username: str) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id,
                   owner_username,
                   code,
                   metadata,
                   created_at,
                   expires_at,
                   max_uses,
                   use_count,
                   signup_count
            FROM referral_codes
            WHERE owner_username = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (owner_username,))
        row = c.fetchone()
    return _referral_code_row_to_dict(row) if row else None


@log_errors()
def ensure_referral_code(owner_username: str,
                         *,
                         metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    existing = get_referral_code(owner_username)
    if existing:
        return existing
    return create_referral_code(owner_username, metadata=metadata)


@log_errors()
def create_referral_code(owner_username: str,
                         *,
                         max_uses: Optional[int] = None,
                         expires_at: Optional[datetime] = None,
                         metadata: Optional[Dict[str, Any]] = None,
                         regenerate: bool = False) -> Dict[str, Any]:
    now = datetime.now()
    normalized_metadata = metadata if isinstance(metadata, dict) else {}

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if regenerate:
            c.execute("DELETE FROM referral_codes WHERE owner_username = ?", (owner_username,))

        code = _generate_referral_code()
        while True:
            c.execute("SELECT 1 FROM referral_codes WHERE code = ?", (code,))
            if not c.fetchone():
                break
            code = _generate_referral_code()

        c.execute("""
            INSERT INTO referral_codes (
                owner_username,
                code,
                metadata,
                created_at,
                expires_at,
                max_uses,
                use_count,
                signup_count
            ) VALUES (?, ?, ?, ?, ?, ?, 0, 0)
        """, (
            owner_username,
            code,
            _dump_json(normalized_metadata),
            now,
            expires_at,
            max_uses,
        ))
        referral_id = c.lastrowid
        conn.commit()

    return get_referral_code(owner_username) or {
        "id": referral_id,
        "owner_username": owner_username,
        "code": code,
        "metadata": normalized_metadata,
        "created_at": _to_datetime_string(now),
        "expires_at": _to_datetime_string(expires_at) if expires_at else None,
        "max_uses": max_uses,
        "use_count": 0,
        "signup_count": 0,
    }


def _get_referral_code_row_by_code(code: str) -> Optional[Tuple[Any, ...]]:
    normalized = _normalize_referral_code(code)
    if not normalized:
        return None
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id,
                   owner_username,
                   code,
                   metadata,
                   created_at,
                   expires_at,
                   max_uses,
                   use_count,
                   signup_count
            FROM referral_codes
            WHERE code = ?
        """, (normalized,))
        return c.fetchone()


@log_errors()
def get_referral_code_by_code(code: str) -> Optional[Dict[str, Any]]:
    row = _get_referral_code_row_by_code(code)
    return _referral_code_row_to_dict(row) if row else None
def record_referral_hit(code: str,
                        *,
                        landing_page: Optional[str] = None,
                        metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    normalized_code = _normalize_referral_code(code)
    if not normalized_code:
        return None

    row = _get_referral_code_row_by_code(normalized_code)
    if not row:
        return None

    referral_id = row[0]
    now = datetime.now()
    normalized_metadata = metadata if isinstance(metadata, dict) else {}

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO referral_hits (referral_code_id, code, landing_page, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            referral_id,
            normalized_code,
            (landing_page or "").strip() or None,
            _dump_json(normalized_metadata),
            now,
        ))
        c.execute("""
            UPDATE referral_codes
            SET use_count = COALESCE(use_count, 0) + 1
            WHERE id = ?
        """, (referral_id,))
        conn.commit()

    return get_referral_overview(row[1])


@log_errors()
def redeem_referral_code(code: str,
                          referred_username: str,
                          *,
                          metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_code = _normalize_referral_code(code)
    if not normalized_code:
        raise ValueError("Invalid referral code")

    row = _get_referral_code_row_by_code(normalized_code)
    if not row:
        raise ValueError("Referral code not found")

    referral_id = row[0]
    owner_username = row[1]
    if owner_username == referred_username:
        raise ValueError("You cannot redeem your own referral code")

    now = datetime.now()
    normalized_metadata = metadata if isinstance(metadata, dict) else {}

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 1
            FROM referral_conversions
            WHERE referred_username = ?
        """, (referred_username,))
        if c.fetchone():
            raise ValueError("Referral already recorded for this user")

        c.execute("""
            INSERT INTO referral_conversions (
                referral_code_id,
                code,
                referrer_username,
                referred_username,
                metadata,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            referral_id,
            normalized_code,
            owner_username,
            referred_username,
            _dump_json(normalized_metadata),
            now,
        ))
        c.execute("""
            UPDATE referral_codes
            SET signup_count = COALESCE(signup_count, 0) + 1
            WHERE id = ?
        """, (referral_id,))
        conn.commit()

    return get_referral_overview(owner_username)


@log_errors()
def get_referral_overview(owner_username: str) -> Dict[str, Any]:
    referral = get_referral_code(owner_username)
    if not referral:
        return {
            "referral": None,
            "metrics": {
                "total_hits": 0,
                "total_conversions": 0,
                "recent_hits": [],
                "landing_summary": [],
            },
        }

    referral_id = referral["id"]
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*)
            FROM referral_hits
            WHERE referral_code_id = ?
        """, (referral_id,))
        total_hits = c.fetchone()[0] or 0

        c.execute("""
            SELECT COUNT(*)
            FROM referral_conversions
            WHERE referral_code_id = ?
        """, (referral_id,))
        total_conversions = c.fetchone()[0] or 0

        c.execute("""
            SELECT landing_page,
                   COUNT(*) AS hits
            FROM referral_hits
            WHERE referral_code_id = ?
            GROUP BY landing_page
            ORDER BY hits DESC
            LIMIT ?
        """, (referral_id, REFERRAL_MAX_LANDING_SUMMARY))
        landing_rows = c.fetchall()

        c.execute("""
            SELECT landing_page,
                   created_at
            FROM referral_hits
            WHERE referral_code_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (referral_id, REFERRAL_MAX_HITS_FETCH))
        recent_rows = c.fetchall()

    landing_summary = [{
        "landing_page": row[0] or "unknown",
        "hits": row[1] or 0,
    } for row in landing_rows]

    recent_hits = [{
        "landing_page": row[0] or "unknown",
        "created_at": _to_datetime_string(row[1]),
    } for row in recent_rows]

    metrics = {
        "total_hits": total_hits,
        "total_conversions": total_conversions,
        "recent_hits": recent_hits,
        "landing_summary": landing_summary,
    }

    return {
        "referral": referral,
        "metrics": metrics,
    }


def _boost_tier_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {
        "id": row[0],
        "server_id": row[1],
        "name": row[2],
        "description": row[3],
        "price_cents": row[4],
        "currency": row[5],
        "benefits": _load_json(row[6], {}),
        "is_active": bool(row[7]),
        "sort_order": row[8] or 0,
        "created_at": _to_datetime_string(row[9]),
        "updated_at": _to_datetime_string(row[10]),
    }


def _boost_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {
        "id": row[0],
        "server_id": row[1],
        "tier_id": row[2],
        "purchaser_username": row[3],
        "status": row[4],
        "started_at": _to_datetime_string(row[5]),
        "expires_at": _to_datetime_string(row[6]),
        "metadata": _load_json(row[7], {}),
        "created_at": _to_datetime_string(row[8]),
    }


def _server_tip_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {
        "id": row[0],
        "server_id": row[1],
        "title": row[2],
        "body": row[3],
        "cta_label": row[4],
        "cta_url": row[5],
        "audience": row[6] or "all",
        "active": bool(row[7]),
        "dismissible": bool(row[8]),
        "priority": row[9] or 0,
        "start_at": _to_datetime_string(row[10]),
        "end_at": _to_datetime_string(row[11]),
        "metadata": _load_json(row[12], {}),
        "created_by": row[13],
        "created_at": _to_datetime_string(row[14]),
        "updated_at": _to_datetime_string(row[15]),
    }
@log_errors()
def create_server_tip(server_id: int,
                       created_by: str,
                       title: str,
                       body: str,
                       *,
                       cta_label: Optional[str] = None,
                       cta_url: Optional[str] = None,
                       audience: str = "all",
                       active: bool = True,
                       dismissible: bool = True,
                       priority: int = 0,
                       start_at: Optional[datetime] = None,
                       end_at: Optional[datetime] = None,
                       metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_title = (title or "").strip()
    normalized_body = (body or "").strip()
    if not normalized_title or not normalized_body:
        raise ValueError("Title and body are required")

    now = datetime.now()
    payload = metadata if isinstance(metadata, dict) else {}

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO server_tips (
                server_id,
                title,
                body,
                cta_label,
                cta_url,
                audience,
                active,
                dismissible,
                priority,
                start_at,
                end_at,
                metadata,
                created_by,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            server_id,
            normalized_title,
            normalized_body,
            (cta_label or "").strip() or None,
            (cta_url or "").strip() or None,
            (audience or "all").strip().lower(),
            1 if active else 0,
            1 if dismissible else 0,
            int(priority or 0),
            start_at,
            end_at,
            _dump_json(payload),
            created_by,
            now,
            now,
        ))
        tip_id = c.lastrowid
        conn.commit()

    return get_server_tip(server_id, tip_id)


@log_errors()
def get_server_tip(server_id: int, tip_id: int) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id,
                   server_id,
                   title,
                   body,
                   cta_label,
                   cta_url,
                   audience,
                   active,
                   dismissible,
                   priority,
                   start_at,
                   end_at,
                   metadata,
                   created_by,
                   created_at,
                   updated_at
            FROM server_tips
            WHERE id = ?
              AND server_id = ?
        """, (tip_id, server_id))
        row = c.fetchone()
    return _server_tip_row_to_dict(row) if row else None


@log_errors()
def update_server_tip(server_id: int,
                      tip_id: int,
                      updates: Dict[str, Any]) -> Dict[str, Any]:
    allowed_fields = {
        "title",
        "body",
        "cta_label",
        "cta_url",
        "audience",
        "active",
        "dismissible",
        "priority",
        "start_at",
        "end_at",
        "metadata",
    }
    if not updates:
        tip = get_server_tip(server_id, tip_id)
        if not tip:
            raise ValueError("Tip not found")
        return tip

    set_clauses: List[str] = []
    params: List[Any] = []
    for key, value in updates.items():
        if key not in allowed_fields:
            continue
        if key in {"active", "dismissible"}:
            value = 1 if bool(value) else 0
        elif key == "metadata":
            value = _dump_json(value if isinstance(value, dict) else {})
        set_clauses.append(f"{key} = ?")
        params.append(value)

    if not set_clauses:
        tip = get_server_tip(server_id, tip_id)
        if not tip:
            raise ValueError("Tip not found")
        return tip

    params.append(datetime.now())
    params.extend([tip_id, server_id])

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(f"""
            UPDATE server_tips
            SET {", ".join(set_clauses)},
                updated_at = ?
            WHERE id = ?
              AND server_id = ?
        """, params)
        conn.commit()

    tip = get_server_tip(server_id, tip_id)
    if not tip:
        raise ValueError("Tip not found")
    return tip


@log_errors()
def delete_server_tip(server_id: int, tip_id: int) -> bool:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM server_tips
            WHERE id = ?
              AND server_id = ?
        """, (tip_id, server_id))
        deleted = c.rowcount > 0
        conn.commit()
    return deleted


@log_errors()
def dismiss_server_tip(tip_id: int, username: str) -> bool:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO server_tip_dismissals (tip_id, username, dismissed_at)
            VALUES (?, ?, ?)
        """, (tip_id, username, datetime.now()))
        conn.commit()
    return True


@log_errors()
def list_server_tips(server_id: int,
                      *,
                      viewer_username: Optional[str] = None,
                      include_inactive: bool = False,
                      include_dismissed: bool = False,
                      limit: int = 20) -> List[Dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 100))
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        join_params: List[Any] = []
        where_clauses = ["t.server_id = ?"]
        time_params: List[Any] = []
        if not include_inactive:
            now = datetime.now()
            where_clauses.append("t.active = 1")
            where_clauses.append("(t.start_at IS NULL OR t.start_at <= ?)")
            where_clauses.append("(t.end_at IS NULL OR t.end_at >= ?)")
            time_params.extend([now, now])

        join_clause = ""
        select_extra = ""
        if viewer_username:
            join_clause = """
                LEFT JOIN server_tip_dismissals d
                  ON d.tip_id = t.id
                 AND d.username = ?
            """
            join_params.append(viewer_username)
            select_extra = ", d.dismissed_at"
            if not include_dismissed:
                where_clauses.append("d.dismissed_at IS NULL")

        query = f"""
            SELECT t.id,
                   t.server_id,
                   t.title,
                   t.body,
                   t.cta_label,
                   t.cta_url,
                   t.audience,
                   t.active,
                   t.dismissible,
                   t.priority,
                   t.start_at,
                   t.end_at,
                   t.metadata,
                   t.created_by,
                   t.created_at,
                   t.updated_at
                   {select_extra}
            FROM server_tips t
            {join_clause}
            WHERE {" AND ".join(where_clauses)}
            ORDER BY t.priority DESC, t.created_at DESC
            LIMIT ?
        """
        params = join_params + [server_id] + time_params + [bounded_limit]
        c.execute(query, params)
        rows = c.fetchall()

    tips: List[Dict[str, Any]] = []
    for row in rows:
        base_row = row[:16]
        tip = _server_tip_row_to_dict(base_row)
        if viewer_username:
            dismissed_at = row[16] if len(row) > 16 else None
            tip["viewer_dismissed"] = bool(dismissed_at)
            if dismissed_at:
                tip["dismissed_at"] = _to_datetime_string(dismissed_at)
        tips.append(tip)
    return tips


@log_errors()
def get_server_tip_dismissals(tip_id: int) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username,
                   dismissed_at
            FROM server_tip_dismissals
            WHERE tip_id = ?
            ORDER BY dismissed_at DESC
        """, (tip_id,))
        rows = c.fetchall()
    return [{
        "username": row[0],
        "dismissed_at": _to_datetime_string(row[1]),
    } for row in rows]


@log_errors()
def record_user_engagement(username: str,
                            event_type: str,
                            *,
                            event_time: Optional[datetime] = None) -> Dict[str, Any]:
    if not username:
        return {}
    event_time = event_time or datetime.now()
    today = event_time.date()

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username,
                   current_streak,
                   longest_streak,
                   last_engaged_date
            FROM user_streaks
            WHERE username = ?
        """, (username,))
        row = c.fetchone()

        if not row:
            current = 1
            longest = 1
            last_date = None
        else:
            last_date = None
            if isinstance(row[3], datetime):
                last_date = row[3].date()
            elif isinstance(row[3], str):
                try:
                    last_date = datetime.fromisoformat(row[3]).date()
                except ValueError:
                    last_date = None

            if last_date == today:
                current = row[1] or 1
                longest = row[2] or current
            elif last_date and (today - last_date).days == 1:
                current = (row[1] or 0) + 1
                longest = max(row[2] or 0, current)
            else:
                current = 1
                longest = max(row[2] or 0, 1)

        c.execute("""
            INSERT INTO user_streaks (username, current_streak, longest_streak, last_engaged_date, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                current_streak = excluded.current_streak,
                longest_streak = excluded.longest_streak,
                last_engaged_date = excluded.last_engaged_date,
                updated_at = excluded.updated_at
        """, (
            username,
            current,
            longest,
            today,
            event_time,
        ))
        conn.commit()

    return {
        "username": username,
        "current_streak": current,
        "longest_streak": longest,
        "last_engaged_date": today.isoformat(),
        "updated_at": _to_datetime_string(event_time),
        "event_type": event_type,
    }
@log_errors()
def get_user_streak(username: str) -> Dict[str, Any]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username,
                   current_streak,
                   longest_streak,
                   last_engaged_date,
                   updated_at
            FROM user_streaks
            WHERE username = ?
        """, (username,))
        row = c.fetchone()

    if not row:
        return {
            "username": username,
            "current_streak": 0,
            "longest_streak": 0,
            "last_engaged_date": None,
            "updated_at": None,
        }

    last_engaged = None
    if isinstance(row[3], datetime):
        last_engaged = row[3].date().isoformat()
    elif isinstance(row[3], str):
        last_engaged = row[3]

    return {
        "username": row[0],
        "current_streak": row[1] or 0,
        "longest_streak": row[2] or 0,
        "last_engaged_date": last_engaged,
        "updated_at": _to_datetime_string(row[4]),
    }


@log_errors()
def create_server_boost_tier(server_id: int,
                             name: str,
                             price_cents: int,
                             *,
                             description: Optional[str] = None,
                             currency: str = "usd",
                             benefits: Optional[Dict[str, Any]] = None,
                             is_active: bool = True,
                             sort_order: int = 0) -> Dict[str, Any]:
    normalized_name = (name or "").strip()
    if not normalized_name:
        raise ValueError("name is required")
    normalized_currency = (currency or "usd").strip().lower()
    price_cents = max(0, int(price_cents))

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        now = datetime.now()
        c.execute("""
            INSERT INTO server_boost_tiers (
                server_id,
                name,
                description,
                price_cents,
                currency,
                benefits,
                is_active,
                sort_order,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            server_id,
            normalized_name,
            (description or "").strip() or None,
            price_cents,
            normalized_currency,
            _dump_json(benefits if isinstance(benefits, dict) else {}),
            1 if is_active else 0,
            int(sort_order),
            now,
            now,
        ))
        tier_id = c.lastrowid
        conn.commit()

    return get_server_boost_tier(server_id, tier_id)


@log_errors()
def list_server_boost_tiers(server_id: int,
                            *,
                            include_inactive: bool = False) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if include_inactive:
            c.execute("""
                SELECT id,
                       server_id,
                       name,
                       description,
                       price_cents,
                       currency,
                       benefits,
                       is_active,
                       sort_order,
                       created_at,
                       updated_at
                FROM server_boost_tiers
                WHERE server_id = ?
                ORDER BY sort_order ASC, created_at ASC
            """, (server_id,))
        else:
            c.execute("""
                SELECT id,
                       server_id,
                       name,
                       description,
                       price_cents,
                       currency,
                       benefits,
                       is_active,
                       sort_order,
                       created_at,
                       updated_at
                FROM server_boost_tiers
                WHERE server_id = ?
                  AND is_active = 1
                ORDER BY sort_order ASC, created_at ASC
            """, (server_id,))
        rows = c.fetchall()
    return [_boost_tier_row_to_dict(row) for row in rows]


@log_errors()
def get_server_boost_tier(server_id: int, tier_id: int) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id,
                   server_id,
                   name,
                   description,
                   price_cents,
                   currency,
                   benefits,
                   is_active,
                   sort_order,
                   created_at,
                   updated_at
            FROM server_boost_tiers
            WHERE server_id = ?
              AND id = ?
        """, (server_id, tier_id))
        row = c.fetchone()
    return _boost_tier_row_to_dict(row) if row else None


@log_errors()
def update_server_boost_tier(server_id: int,
                             tier_id: int,
                             updates: Dict[str, Any]) -> Dict[str, Any]:
    allowed_fields = {
        "name",
        "description",
        "price_cents",
        "currency",
        "benefits",
        "is_active",
        "sort_order",
    }
    if not updates:
        tier = get_server_boost_tier(server_id, tier_id)
        if not tier:
            raise ValueError("Tier not found")
        return tier

    set_clauses: List[str] = []
    params: List[Any] = []
    for key, value in updates.items():
        if key not in allowed_fields:
            continue
        if key == "price_cents":
            value = max(0, int(value))
        elif key == "currency":
            value = str(value).strip().lower()
        elif key == "benefits":
            value = _dump_json(value if isinstance(value, dict) else {})
        elif key == "is_active":
            value = 1 if bool(value) else 0
        else:
            value = str(value).strip() if value is not None else None
        set_clauses.append(f"{key} = ?")
        params.append(value)

    if not set_clauses:
        tier = get_server_boost_tier(server_id, tier_id)
        if not tier:
            raise ValueError("Tier not found")
        return tier

    params.append(datetime.now())
    params.extend([server_id, tier_id])

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(f"""
            UPDATE server_boost_tiers
            SET {", ".join(set_clauses)},
                updated_at = ?
            WHERE server_id = ?
              AND id = ?
        """, params)
        conn.commit()

    tier = get_server_boost_tier(server_id, tier_id)
    if not tier:
        raise ValueError("Tier not found")
    return tier
@log_errors()
def delete_server_boost_tier(server_id: int, tier_id: int) -> bool:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM server_boost_tiers
            WHERE server_id = ?
              AND id = ?
        """, (server_id, tier_id))
        deleted = c.rowcount > 0
        conn.commit()
    return deleted
@log_errors()
def activate_server_boost(server_id: int,
                          tier_id: int,
                          purchaser_username: str,
                          *,
                          duration_days: int = 30,
                          metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if duration_days <= 0 or duration_days > BOOST_MAX_DURATION_DAYS:
        raise ValueError("duration_days must be between 1 and 90")

    tier = get_server_boost_tier(server_id, tier_id)
    if not tier or not tier.get("is_active"):
        raise ValueError("Boost tier is not available")

    now = datetime.now()
    expires_at = now + timedelta(days=duration_days)
    payload = metadata if isinstance(metadata, dict) else {}

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO server_boosts (
                server_id,
                tier_id,
                purchaser_username,
                status,
                started_at,
                expires_at,
                metadata,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            server_id,
            tier_id,
            purchaser_username,
            BOOST_STATUS_ACTIVE,
            now,
            expires_at,
            _dump_json(payload),
            now,
        ))
        boost_id = c.lastrowid
        conn.commit()

    return get_server_boost(server_id, boost_id)


@log_errors()
def get_server_boost(server_id: int, boost_id: int) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id,
                   server_id,
                   tier_id,
                   purchaser_username,
                   status,
                   started_at,
                   expires_at,
                   metadata,
                   created_at
            FROM server_boosts
            WHERE server_id = ?
              AND id = ?
        """, (server_id, boost_id))
        row = c.fetchone()
    return _boost_row_to_dict(row) if row else None


@log_errors()
def list_server_boosts(server_id: int,
                       *,
                       status: Optional[str] = None,
                       include_expired: bool = False,
                       limit: int = 50) -> List[Dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 200))
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        params: List[Any] = [server_id]
        where_clauses = ["server_id = ?"]
        if status:
            where_clauses.append("status = ?")
            params.append(status.strip().lower())
        if not include_expired:
            where_clauses.append("(expires_at IS NULL OR expires_at >= ?)")
            params.append(datetime.now())

        query = f"""
            SELECT id,
                   server_id,
                   tier_id,
                   purchaser_username,
                   status,
                   started_at,
                   expires_at,
                   metadata,
                   created_at
            FROM server_boosts
            WHERE {" AND ".join(where_clauses)}
            ORDER BY created_at DESC
            LIMIT ?
        """
        params.append(bounded_limit)
        c.execute(query, params)
        rows = c.fetchall()
    return [_boost_row_to_dict(row) for row in rows]


@log_errors()
def cancel_server_boost(server_id: int, boost_id: int, *, status: str = BOOST_STATUS_CANCELLED) -> Dict[str, Any]:
    normalized_status = (status or BOOST_STATUS_CANCELLED).strip().lower()
    if normalized_status not in {BOOST_STATUS_CANCELLED, BOOST_STATUS_EXPIRED, BOOST_STATUS_ACTIVE}:
        normalized_status = BOOST_STATUS_CANCELLED

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE server_boosts
            SET status = ?, expires_at = CASE WHEN expires_at IS NULL OR expires_at > ? THEN ? ELSE expires_at END
            WHERE server_id = ?
              AND id = ?
        """, (
            normalized_status,
            datetime.now(),
            datetime.now(),
            server_id,
            boost_id,
        ))
        conn.commit()

    boost = get_server_boost(server_id, boost_id)
    if not boost:
        raise ValueError("Boost not found after update")
    return boost


@log_errors()
def get_billing_usage(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    start = start or datetime.now() - timedelta(days=30)
    end = end or datetime.now()
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT s.slug,
                   t.name,
                   COUNT(b.id) AS boost_count
            FROM server_boosts b
            JOIN servers s ON s.id = b.server_id
            JOIN server_boost_tiers t ON t.id = b.tier_id
            WHERE b.created_at BETWEEN ? AND ?
            GROUP BY s.slug, t.name
        """, (start, end))
        boost_rows = c.fetchall()

        c.execute("""
            SELECT s.slug,
                   SUM(l.premium_clicks) AS premium_clicks,
                   SUM(l.premium_impressions) AS premium_impressions
            FROM listing_analytics l
            JOIN listings li ON li.id = l.listing_id
            JOIN servers s ON s.owner_username = li.user_id
            WHERE l.created_at BETWEEN ? AND ?
            GROUP BY s.slug
        """, (start, end))
        listing_rows = c.fetchall()

    listing_map = {row[0]: {"premium_clicks": row[1] or 0, "premium_impressions": row[2] or 0} for row in listing_rows}
    usage: List[Dict[str, Any]] = []
    for row in boost_rows:
        stats = listing_map.get(row[0], {"premium_clicks": 0, "premium_impressions": 0})
        usage.append({
            "server_slug": row[0],
            "tier_name": row[1],
            "boost_count": row[2],
            "premium_clicks": stats["premium_clicks"],
            "premium_impressions": stats["premium_impressions"],
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
        })
    return usage


def _moderation_alert_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    details = _load_json(row[5], {})
    return {
        "id": row[0],
        "server_id": row[1],
        "alert_type": row[2],
        "severity": row[3],
        "message": row[4],
        "details": details if isinstance(details, dict) else {},
        "status": row[6],
        "triggered_at": _to_datetime_string(row[7]),
        "resolved_at": _to_datetime_string(row[8]),
        "resolved_by": row[9],
    }


def _collect_text_fragments(payload: Dict[str, Any]) -> List[str]:
    fragments: List[str] = []
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str):
            fragments.append(value)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                if isinstance(item, str):
                    fragments.append(item)
        elif isinstance(value, dict):
            nested = _collect_text_fragments(value)
            if nested:
                fragments.extend(nested)
    return fragments


def _tokenize_moderation_text(text: str) -> List[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    tokens = []
    for token in normalized.split():
        if len(token) < 4:
            continue
        if token in MODERATION_SUGGESTION_STOPWORDS:
            continue
        if token.startswith("http"):
            continue
        tokens.append(token)
    return tokens


def _get_server_identity(server_id: int) -> Tuple[str, str]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT slug, name
            FROM servers
            WHERE id = ?
        """, (server_id,))
        row = c.fetchone()
    if not row:
        raise ValueError("Server not found.")
    slug = row[0] or ""
    name = row[1] or slug or f"server:{server_id}"
    return str(slug), str(name)


def _resolve_alerts_by_type(server_id: int, alert_type: str, resolver_username: Optional[str] = None) -> int:
    normalized = (alert_type or "").strip().lower()
    if not normalized:
        return 0
    timestamp = datetime.now()
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE moderation_alerts
            SET status = 'resolved',
                resolved_at = ?,
                resolved_by = ?
            WHERE server_id = ?
              AND LOWER(alert_type) = ?
              AND status = 'open'
        """, (timestamp, resolver_username, server_id, normalized))
        affected = c.rowcount
        if affected:
            conn.commit()
        return affected


def _extract_server_context(context_payload: Optional[Dict[str, Any]]) -> Optional[int]:
    if not context_payload or not isinstance(context_payload, dict):
        return None

    server_candidates: List[int] = []
    slug_candidates: List[str] = []
    channel_candidates: List[int] = []

    def _coerce_int(value: Any) -> Optional[int]:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            try:
                number = int(value)
            except (TypeError, ValueError):
                return None
            return number if number > 0 else None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if stripped.isdigit():
                number = int(stripped)
                return number if number > 0 else None
            lowered = stripped.lower()
            if lowered.startswith("server:"):
                suffix = lowered.split("server:", 1)[1].strip()
                if suffix.isdigit():
                    number = int(suffix)
                    return number if number > 0 else None
        return None

    def _coerce_slug(value: Any) -> Optional[str]:
        if isinstance(value, str):
            slug = value.strip()
            if slug:
                return slug.lower()
        return None

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if value is None:
                    continue
                key_lower = str(key).lower()
                if key_lower in {"server_id", "serverid"}:
                    candidate = _coerce_int(value)
                    if candidate:
                        server_candidates.append(candidate)
                    continue
                if key_lower in {"server", "server_slug", "serverslug"}:
                    candidate = _coerce_int(value)
                    if candidate:
                        server_candidates.append(candidate)
                    slug_candidate = _coerce_slug(value)
                    if slug_candidate:
                        slug_candidates.append(slug_candidate)
                    if isinstance(value, dict):
                        nested_id = _coerce_int(value.get("id"))
                        if nested_id:
                            server_candidates.append(nested_id)
                        nested_slug = _coerce_slug(value.get("slug"))
                        if nested_slug:
                            slug_candidates.append(nested_slug)
                        _walk(value)
                    continue
                if key_lower in {"channel_id", "channelid"}:
                    channel_candidate = _coerce_int(value)
                    if channel_candidate:
                        channel_candidates.append(channel_candidate)
                    continue
                if isinstance(value, (dict, list, tuple, set)):
                    _walk(value)
        elif isinstance(obj, (list, tuple, set)):
            for item in obj:
                _walk(item)

    _walk(context_payload)

    for candidate in server_candidates:
        if candidate:
            return candidate

    unique_slugs: List[str] = []
    seen_slugs = set()
    for slug in slug_candidates:
        if slug and slug not in seen_slugs:
            seen_slugs.add(slug)
            unique_slugs.append(slug)

    unique_channels: List[int] = []
    seen_channels = set()
    for channel_id in channel_candidates:
        if channel_id and channel_id not in seen_channels:
            seen_channels.add(channel_id)
            unique_channels.append(channel_id)

    if not unique_slugs and not unique_channels:
        return None

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        for slug in unique_slugs:
            c.execute(
                """
                SELECT id
                FROM servers
                WHERE LOWER(slug) = ?
                LIMIT 1
                """,
                (slug,),
            )
            row = c.fetchone()
            if row and row[0]:
                try:
                    return int(row[0])
                except (TypeError, ValueError):
                    continue
        for channel_id in unique_channels:
            c.execute(
                """
                SELECT server_id
                FROM server_channels
                WHERE id = ?
                LIMIT 1
                """,
                (channel_id,),
            )
            row = c.fetchone()
            if row and row[0]:
                try:
                    return int(row[0])
                except (TypeError, ValueError):
                    continue

    return None


@log_errors()
def create_moderation_alert(
    server_id: int,
    alert_type: str,
    *,
    severity: Optional[str] = None,
    message: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    dedupe_window_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        server_id_value = int(server_id)
    except (TypeError, ValueError):
        raise ValueError("server_id must be an integer")
    if server_id_value <= 0:
        raise ValueError("server_id must be positive")

    normalized_type = (alert_type or "").strip().lower()
    if not normalized_type:
        raise ValueError("alert_type is required")

    normalized_severity = (severity or "warning").strip().lower()
    if normalized_severity not in {"info", "warning", "critical", "error"}:
        normalized_severity = "warning"

    message_value = (message or "").strip() or None
    details_payload = details if isinstance(details, dict) else {}
    details_json = _dump_json(details_payload)
    now = datetime.now()

    window_cutoff: Optional[datetime] = None
    if dedupe_window_minutes:
        try:
            window_minutes = max(1, int(dedupe_window_minutes))
        except (TypeError, ValueError):
            window_minutes = None
        if window_minutes:
            window_cutoff = now - timedelta(minutes=window_minutes)

    with get_pool().get_connection() as conn:
        c = conn.cursor()

        existing_row: Optional[Tuple[Any, ...]] = None
        if window_cutoff:
            c.execute(
                """
                SELECT id,
                       server_id,
                       alert_type,
                       severity,
                       message,
                       details,
                       status,
                       triggered_at,
                       resolved_at,
                       resolved_by
                FROM moderation_alerts
                WHERE server_id = ?
                  AND LOWER(alert_type) = ?
                  AND status = 'open'
                  AND triggered_at >= ?
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (server_id_value, normalized_type, window_cutoff),
            )
            existing_row = c.fetchone()

        if existing_row:
            c.execute(
                """
                UPDATE moderation_alerts
                SET severity = ?,
                    message = ?,
                    details = ?,
                    triggered_at = ?
                WHERE id = ?
                """,
                (
                    normalized_severity,
                    message_value,
                    details_json,
                    now,
                    existing_row[0],
                ),
            )
            conn.commit()
            c.execute(
                """
                SELECT id,
                       server_id,
                       alert_type,
                       severity,
                       message,
                       details,
                       status,
                       triggered_at,
                       resolved_at,
                       resolved_by
                FROM moderation_alerts
                WHERE id = ?
                """,
                (existing_row[0],),
            )
            row = c.fetchone()
            if row:
                return _moderation_alert_row_to_dict(row)

        c.execute(
            """
            INSERT INTO moderation_alerts (
                server_id,
                alert_type,
                severity,
                message,
                details,
                status,
                triggered_at
            ) VALUES (?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                server_id_value,
                normalized_type,
                normalized_severity,
                message_value,
                details_json,
                now,
            ),
        )
        alert_id = c.lastrowid
        conn.commit()
        c.execute(
            """
            SELECT id,
                   server_id,
                   alert_type,
                   severity,
                   message,
                   details,
                   status,
                   triggered_at,
                   resolved_at,
                   resolved_by
            FROM moderation_alerts
            WHERE id = ?
            """,
            (alert_id,),
        )
        inserted_row = c.fetchone()

    if inserted_row:
        return _moderation_alert_row_to_dict(inserted_row)

    return {
        "id": alert_id,
        "server_id": server_id_value,
        "alert_type": normalized_type,
        "severity": normalized_severity,
        "message": message_value,
        "details": details_payload,
        "status": "open",
        "triggered_at": _to_datetime_string(now),
        "resolved_at": None,
        "resolved_by": None,
    }


def _evaluate_report_escalation(server_id: Optional[int], context_payload: Optional[Dict[str, Any]]) -> None:
    if server_id is None:
        server_id = _extract_server_context(context_payload)
    if server_id is None:
        return

    try:
        slug, name = _get_server_identity(server_id)
    except ValueError:
        return
    try:
        slug, name = _get_server_identity(server_id)
    except ValueError:
        return
    pattern = f'%\\"server_slug\\": \\"{slug.lower()}\\"%'
    now = datetime.now()
    recent_cutoff = now - timedelta(minutes=MODERATION_REPORT_SPIKE_RECENT_MINUTES)
    window_cutoff = now - timedelta(minutes=MODERATION_REPORT_SPIKE_WINDOW_MINUTES)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT COUNT(*)
            FROM reports
            WHERE LOWER(context) LIKE ?
              AND status IN (?, ?)
        """, (pattern, REPORT_STATUS_PENDING, REPORT_STATUS_REVIEWING))
        open_row = c.fetchone()
        open_count = open_row[0] if open_row else 0

        c.execute(f"""
            SELECT COUNT(*)
            FROM reports
            WHERE LOWER(context) LIKE ?
              AND created_at >= ?
        """, (pattern, recent_cutoff))
        recent_row = c.fetchone()
        recent_count = recent_row[0] if recent_row else 0

        c.execute(f"""
            SELECT COUNT(*)
            FROM reports
            WHERE LOWER(context) LIKE ?
              AND created_at >= ?
        """, (pattern, window_cutoff))
        window_row = c.fetchone()
        window_count = window_row[0] if window_row else 0

    threshold_met = (
        open_count >= MODERATION_REPORT_SPIKE_OPEN_THRESHOLD
        or recent_count >= MODERATION_REPORT_SPIKE_RECENT_THRESHOLD
    )

    if threshold_met:
        details = {
            "open_reports": open_count,
            "recent_reports": recent_count,
            "window_reports": window_count,
            "recent_window_minutes": MODERATION_REPORT_SPIKE_RECENT_MINUTES,
            "window_minutes": MODERATION_REPORT_SPIKE_WINDOW_MINUTES,
            "server_slug": slug,
            "server_name": name,
        }
        message = (
            f"Spike in reports: {open_count} open, {recent_count} in the last "
            f"{MODERATION_REPORT_SPIKE_RECENT_MINUTES} minutes."
        )
        severity = "critical" if open_count >= MODERATION_REPORT_SPIKE_OPEN_THRESHOLD + 3 else "warning"
        create_moderation_alert(
            server_id,
            "report_spike",
            severity=severity,
            message=message,
            details=details,
            dedupe_window_minutes=MODERATION_REPORT_SPIKE_RECENT_MINUTES,
        )
    else:
        _resolve_alerts_by_type(server_id, "report_spike")


@log_errors()
def get_moderation_keyword_suggestions(server_id: int,
                                       window_hours: int = 72,
                                       limit: int = 10) -> List[Dict[str, Any]]:
    window_hours = max(1, min(int(window_hours), 24 * 30))
    limit = max(1, min(int(limit), 50))

    try:
        slug, _ = _get_server_identity(server_id)
    except ValueError:
        return []

    slug_lower = slug.lower()
    cutoff = datetime.now() - timedelta(hours=window_hours)

    slug_terms = {part for part in re.split(r"[^a-z0-9]+", slug_lower) if len(part) >= 3}
    ignore_terms = MODERATION_SUGGESTION_STOPWORDS.union(slug_terms)

    term_counts: Dict[str, int] = {}

    reports_payload = list_reports(limit=500, server_slug=slug_lower)
    for report in reports_payload.get("reports", []):
        created_at = _parse_db_datetime(report.get("created_at"))
        if not created_at or created_at < cutoff:
            continue
        context = report.get("context") or {}
        if not isinstance(context, dict):
            continue
        for fragment in _collect_text_fragments(context):
            for token in _tokenize_moderation_text(fragment):
                if token in ignore_terms:
                    continue
                term_counts[token] = term_counts.get(token, 0) + 1

    actions_payload = list_moderation_actions(server_id, limit=500)
    for action in actions_payload.get("actions", []):
        created_at = _parse_db_datetime(action.get("created_at"))
        if not created_at or created_at < cutoff:
            continue
        reason = action.get("reason")
        if isinstance(reason, str):
            for token in _tokenize_moderation_text(reason):
                if token in ignore_terms:
                    continue
                term_counts[token] = term_counts.get(token, 0) + 1
        metadata = action.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = _load_json(metadata, {})
        if isinstance(metadata, dict):
            for fragment in _collect_text_fragments(metadata):
                for token in _tokenize_moderation_text(fragment):
                    if token in ignore_terms:
                        continue
                    term_counts[token] = term_counts.get(token, 0) + 1

    if not term_counts:
        return []

    existing_filters = set()
    try:
        for entry in get_server_keyword_filters(server_id):
            phrase = entry.get("phrase")
            if phrase:
                existing_filters.add(str(phrase).lower())
    except Exception:
        pass

    ranked_terms = sorted(
        term_counts.items(),
        key=lambda item: (-item[1], item[0]),
    )

    suggestions: List[Dict[str, Any]] = []
    for term, count in ranked_terms:
        if term in existing_filters:
            continue
        suggestions.append({
            "term": term,
            "count": count,
            "source": "reports",
            "window_hours": window_hours,
        })
        if len(suggestions) >= limit:
            break

    return suggestions


@log_errors()
def create_report(reporter_username: Optional[str],
                  target_type: str,
                  target_id: str,
                  context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_type = (target_type or "").strip().lower()
    if not normalized_type:
        raise ValueError("target_type is required")
    normalized_id = (target_id or "").strip()
    if not normalized_id:
        raise ValueError("target_id is required")
    payload = context if isinstance(context, dict) else {}
    timestamp = datetime.now()

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO reports (
                reporter_username,
                target_type,
                target_id,
                context,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            reporter_username,
            normalized_type,
            normalized_id,
            _dump_json(payload),
            REPORT_STATUS_PENDING,
            timestamp,
        ))
        report_id = c.lastrowid
        conn.commit()

    try:
        _evaluate_report_escalation(None, payload if isinstance(payload, dict) else {})
    except Exception as exc:
        logger.debug(f"Failed to evaluate report escalation: {exc}")

    return {
        "id": report_id,
        "reporter_username": reporter_username,
        "target_type": normalized_type,
        "target_id": normalized_id,
        "context": payload,
        "status": REPORT_STATUS_PENDING,
        "created_at": _to_datetime_string(timestamp),
        "resolved_at": None,
    }


@log_errors()
def list_reports(limit: int = 50,
                 offset: int = 0,
                 statuses: Optional[Sequence[str]] = None,
                 target_type: Optional[str] = None,
                 server_slug: Optional[str] = None) -> Dict[str, Any]:
    bounded_limit = max(1, min(int(limit), 200))
    bounded_offset = max(0, int(offset))

    normalized_statuses: List[str] = []
    if statuses:
        for status in statuses:
            normalized = (status or "").strip().lower()
            if normalized in REPORT_STATUSES and normalized not in normalized_statuses:
                normalized_statuses.append(normalized)

    where_clauses: List[str] = []
    params: List[Any] = []

    if normalized_statuses:
        placeholders = ", ".join("?" * len(normalized_statuses))
        where_clauses.append(f"status IN ({placeholders})")
        params.extend(normalized_statuses)

    if target_type:
        where_clauses.append("LOWER(target_type) = ?")
        params.append((target_type or "").strip().lower())

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    query_sql = f"""
        SELECT id,
               reporter_username,
               target_type,
               target_id,
               context,
               status,
               created_at,
               resolved_at
        FROM reports
        {where_sql}
        ORDER BY created_at DESC, id DESC
    """

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql(query_sql), params)
        rows = c.fetchall()

    reports: List[Dict[str, Any]] = []
    for row in rows:
        context = _load_json(row[4], {})
        if not isinstance(context, dict):
            context = {}

        if server_slug:
            context_slug = context.get("server_slug") or context.get("server") or context.get("serverSlug")
            if context_slug and str(context_slug).lower() != str(server_slug).lower():
                continue

        reports.append({
            "id": row[0],
            "reporter_username": row[1],
            "target_type": row[2],
            "target_id": row[3],
            "context": context,
            "status": row[5],
            "created_at": _to_datetime_string(row[6]),
            "resolved_at": _to_datetime_string(row[7]),
        })

    total = len(reports)
    slice_start = min(bounded_offset, total)
    slice_end = min(slice_start + bounded_limit, total)
    paginated = reports[slice_start:slice_end]

    return {
        "reports": paginated,
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
    }


@log_errors()
def get_report_by_id(report_id: int) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id,
                   reporter_username,
                   target_type,
                   target_id,
                   context,
                   status,
                   created_at,
                   resolved_at
            FROM reports
            WHERE id = ?
        """, (report_id,))
        row = c.fetchone()

    if not row:
        return None

    context = _load_json(row[4], {})
    return {
        "id": row[0],
        "reporter_username": row[1],
        "target_type": row[2],
        "target_id": row[3],
        "context": context if isinstance(context, dict) else {},
        "status": row[5],
        "created_at": _to_datetime_string(row[6]),
        "resolved_at": _to_datetime_string(row[7]),
    }


@log_errors()
def update_report_status(report_id: int, status: str,
                         resolved_at: Optional[datetime] = None) -> Dict[str, Any]:
    normalized_status = (status or "").strip().lower()
    if normalized_status not in REPORT_STATUSES:
        raise ValueError("Unsupported report status")

    timestamp = resolved_at or (datetime.now() if normalized_status in {REPORT_STATUS_RESOLVED, REPORT_STATUS_DISMISSED} else None)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE reports
            SET status = ?,
                resolved_at = ?
            WHERE id = ?
        """, (normalized_status, timestamp, report_id))
        if c.rowcount == 0:
            raise ValueError("Report not found")
        conn.commit()

    report = get_report_by_id(report_id)
    if report:
        report["status"] = normalized_status
        report["resolved_at"] = _to_datetime_string(timestamp) if timestamp else None
        try:
            _evaluate_report_escalation(None, report.get("context"))
        except Exception as exc:
            logger.debug(f"Failed to re-evaluate report escalation: {exc}")
    return report or {
        "id": report_id,
        "status": normalized_status,
        "resolved_at": _to_datetime_string(timestamp) if timestamp else None,
    }


def _normalize_user_list(usernames: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    seen: set[str] = set()
    for username in usernames:
        if username is None:
            continue
        value = str(username).strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _normalize_int_list(values: Iterable[Any]) -> List[int]:
    normalized: List[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number < 0 or number in seen:
            continue
        normalized.append(number)
        seen.add(number)
    return normalized


def _derive_dm_title(conversation_type: str, participants: Sequence[Dict[str, Any]],
                     viewer_username: Optional[str], explicit_title: Optional[str]) -> str:
    if explicit_title:
        return explicit_title

    active_participants = [p for p in participants if not p.get("left_at")]

    if conversation_type == "direct":
        for participant in active_participants:
            if participant["username"] != viewer_username:
                return participant.get("display_name") or participant["username"]

    names: List[str] = []
    for participant in active_participants:
        display = participant.get("display_name") or participant["username"]
        if viewer_username and participant["username"] == viewer_username:
            continue
        names.append(display)

    if not names:
        names = [
            (participant.get("display_name") or participant["username"])
            for participant in active_participants
        ]

    if names:
        if len(names) > 3:
            return ", ".join(names[:3]) + "…"
        return ", ".join(names)

    return "Conversation"


def _enrich_dm_rich_content(message_type: str, payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not payload or not isinstance(payload, dict):
        return None

    if message_type == "listing":
        listing_id = payload.get("listing_id")
        if listing_id is None:
            return None
        listing = get_listing_by_id(listing_id)
        if not listing:
            return None
        return {
            "type": "listing",
            "listing_id": listing_id,
            "title": listing.get("title"),
            "price": listing.get("price"),
            "link": listing.get("link"),
            "source": listing.get("source"),
            "image_url": listing.get("image_url"),
            "created_at": listing.get("created_at"),
        }

    if message_type == "saved_search":
        saved_search_id = payload.get("saved_search_id")
        if saved_search_id is None:
            return None
        saved = get_saved_search_by_id(saved_search_id)
        if not saved:
            return None
        return {
            "type": "saved_search",
            "saved_search_id": saved_search_id,
            "name": saved.get("name"),
            "keywords": saved.get("keywords"),
            "location": saved.get("location"),
            "radius": saved.get("radius"),
            "min_price": saved.get("min_price"),
            "max_price": saved.get("max_price"),
        }

    if message_type == "quick_reply":
        return {
            "type": "quick_reply",
            "template_key": payload.get("template_key"),
            "label": payload.get("label") or payload.get("template_key") or "Quick reply",
            "body": payload.get("body"),
        }

    if message_type == "attachment":
        enriched = dict(payload)
        enriched.setdefault("type", "attachment")
        return enriched

    return None


def _build_dm_message_from_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    message_type = row[4] or "text"
    rich_payload = _load_json(row[7], {})
    if not isinstance(rich_payload, dict):
        rich_payload = {}

    message = {
        "id": row[0],
        "conversation_id": row[1],
        "sender_id": row[2],
        "body": row[3] or "",
        "message_type": message_type,
        "created_at": _to_datetime_string(row[5]),
        "display_name": row[6],
        "rich_content": rich_payload,
    }

    preview = _enrich_dm_rich_content(message_type, rich_payload)
    if preview:
        message["rich_preview"] = preview

    return message


def _is_active_dm_participant(cursor, conversation_id: int, username: str) -> bool:
    cursor.execute("""
        SELECT 1
        FROM dm_participants
        WHERE conversation_id = ?
          AND username = ?
          AND (left_at IS NULL)
    """, (conversation_id, username))
    return cursor.fetchone() is not None
def _find_existing_direct_conversation(cursor, user_a: str, user_b: str) -> Optional[int]:
    cursor.execute("""
        SELECT c.id
        FROM dm_conversations c
        WHERE c.conversation_type = 'direct'
          AND EXISTS (
              SELECT 1 FROM dm_participants p1
              WHERE p1.conversation_id = c.id
                AND p1.username = ?
                AND p1.left_at IS NULL
          )
          AND EXISTS (
              SELECT 1 FROM dm_participants p2
              WHERE p2.conversation_id = c.id
                AND p2.username = ?
                AND p2.left_at IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM dm_participants px
              WHERE px.conversation_id = c.id
                AND px.username NOT IN (?, ?)
                AND px.left_at IS NULL
          )
        ORDER BY COALESCE(c.last_message_at, c.created_at) DESC
        LIMIT 1
    """, (user_a, user_b, user_a, user_b))
    row = cursor.fetchone()
    if not row:
        return None
    return row[0]


@log_errors()
def is_user_in_dm_conversation(username: str, conversation_id: int) -> bool:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 1
            FROM dm_participants
            WHERE conversation_id = ?
              AND username = ?
              AND (left_at IS NULL)
        """, (conversation_id, username))
        row = c.fetchone()
    return bool(row)
def create_dm_conversation(creator_username: str, participant_usernames: Sequence[str],
                          title: Optional[str] = None,
                          metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not creator_username:
        raise ValueError("Creator username is required")

    participants = _normalize_user_list(list(participant_usernames) + [creator_username])
    if len(participants) < 2:
        raise ValueError("At least two unique participants are required")

    conversation_type = "group" if len(participants) > 2 else "direct"
    if conversation_type == "direct":
        other_username = next((name for name in participants if name != creator_username), None)
        if not other_username:
            raise ValueError("You must include another participant.")
        if not are_friends(creator_username, other_username):
            raise ValueError("You must be friends before starting a direct message.")
    metadata_json = _dump_json(metadata) if metadata else None
    now = datetime.now()

    with get_pool().get_connection() as conn:
        c = conn.cursor()

        for username in participants:
            if username == creator_username:
                continue
            if _are_users_blocked(c, creator_username, username):
                raise ValueError("Cannot create a conversation with a blocked user.")

        if conversation_type == "direct":
            pair = sorted(participants)[:2]
            existing_id = _find_existing_direct_conversation(c, pair[0], pair[1])
            if existing_id:
                return get_dm_conversation(existing_id, creator_username)

        c.execute("""
            INSERT INTO dm_conversations (conversation_type, title, created_by, metadata, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (conversation_type, title, creator_username, metadata_json, now))
        conversation_id = c.lastrowid

        for username in participants:
            role = "owner" if username == creator_username else "member"
            c.execute("""
                INSERT OR IGNORE INTO dm_participants (conversation_id, username, role, joined_at, last_active_at)
                VALUES (?, ?, ?, ?, ?)
            """, (conversation_id, username, role, now, now if username == creator_username else None))

        c.execute("""
            UPDATE dm_participants
            SET left_at = NULL,
                last_active_at = COALESCE(last_active_at, ?),
                joined_at = CASE
                    WHEN left_at IS NOT NULL THEN ?
                    ELSE joined_at
                END
            WHERE conversation_id = ? AND username = ?
        """, (
            now if username == creator_username else None,
            now,
            conversation_id,
            username,
        ))

        conn.commit()

    try:
        log_profile_activity(
            creator_username,
            "dm_conversation_created",
            entity_id=str(conversation_id),
            metadata={"type": conversation_type, "participant_count": len(participants)},
            visibility="connections",
        )
    except Exception:
        pass

    return get_dm_conversation(conversation_id, creator_username)


@log_errors()
def ensure_dm_conversation_between(user_a: str, user_b: str) -> Optional[Dict[str, Any]]:
    """
    Ensure a direct-message conversation exists between two users.
    Returns the conversation payload as seen by user_a.
    """
    if not user_a or not user_b or user_a == user_b:
        return None
    return create_dm_conversation(user_a, [user_b])


@log_errors()
def rename_dm_conversation(conversation_id: int, actor_username: str, title: str) -> Dict[str, Any]:
    clean_title = (title or "").strip()
    if not clean_title:
        raise ValueError("Title is required.")
    clean_title = clean_title[:120]

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT conversation_type, created_by
            FROM dm_conversations
            WHERE id = ?
        """, (conversation_id,))
        row = c.fetchone()
        if not row:
            raise ValueError("Conversation not found.")
        conversation_type = row[0]
        created_by = row[1]
        if conversation_type != "group":
            raise ValueError("Only group conversations can be renamed.")

        c.execute("""
            SELECT role, left_at
            FROM dm_participants
            WHERE conversation_id = ? AND username = ?
        """, (conversation_id, actor_username))
        membership = c.fetchone()
        if not membership:
            raise ValueError("You are not part of this conversation.")
        role, left_at = membership
        if left_at is not None:
            raise ValueError("You have already left this conversation.")
        role = (role or "member").lower()
        if role != "owner" and actor_username != created_by:
            raise ValueError("Insufficient permissions to rename this conversation.")

        c.execute("""
            UPDATE dm_conversations
            SET title = ?
            WHERE id = ?
        """, (clean_title, conversation_id))
        if c.rowcount == 0:
            raise ValueError("Conversation not found.")
        conn.commit()

    try:
        log_profile_activity(
            actor_username,
            "dm_conversation_renamed",
            entity_id=str(conversation_id),
            metadata={"title": clean_title},
            visibility="private",
        )
    except Exception:
        pass

    conversation = get_dm_conversation(conversation_id, actor_username)
    if conversation:
        conversation["title"] = clean_title
    return conversation or {"id": conversation_id, "title": clean_title}


@log_errors()
def leave_dm_conversation(conversation_id: int, username: str) -> bool:
    if not username:
        raise ValueError("Username is required.")

    now = datetime.now()
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT conversation_type
            FROM dm_conversations
            WHERE id = ?
        """, (conversation_id,))
        convo_row = c.fetchone()
        if not convo_row:
            raise ValueError("Conversation not found.")
        conversation_type = convo_row[0]
        if conversation_type == "direct":
            raise ValueError("You cannot leave a direct conversation.")

        c.execute("""
            SELECT role, left_at
            FROM dm_participants
            WHERE conversation_id = ? AND username = ?
        """, (conversation_id, username))
        membership = c.fetchone()
        if not membership:
            raise ValueError("You are not part of this conversation.")
        role, left_at = membership
        if left_at is not None:
            return False

        c.execute("""
            UPDATE dm_participants
            SET left_at = ?
            WHERE conversation_id = ? AND username = ?
        """, (now, conversation_id, username))

        if role and role.lower() == "owner":
            c.execute("""
                SELECT username
                FROM dm_participants
                WHERE conversation_id = ?
                  AND username != ?
                  AND left_at IS NULL
                ORDER BY joined_at ASC
                LIMIT 1
            """, (conversation_id, username))
            successor = c.fetchone()
            if successor:
                c.execute("""
                    UPDATE dm_participants
                    SET role = 'owner'
                    WHERE conversation_id = ? AND username = ?
                """, (conversation_id, successor[0]))

        conn.commit()

    try:
        log_profile_activity(
            username,
            "dm_conversation_left",
            entity_id=str(conversation_id),
            metadata={},
            visibility="private",
        )
    except Exception:
        pass

    return True
@log_errors()
def list_dm_conversations(username: str, limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT c.id
            FROM dm_conversations c
            JOIN dm_participants p ON p.conversation_id = c.id
            WHERE p.username = ?
              AND (p.left_at IS NULL)
            ORDER BY COALESCE(c.last_message_at, c.created_at) DESC
            LIMIT ?
        """, (username, limit))
        rows = c.fetchall()

    conversations: List[Dict[str, Any]] = []
    for row in rows:
        conversation = get_dm_conversation(row[0], username)
        if conversation:
            conversations.append(conversation)
    return conversations


@log_errors()
def get_dm_conversation(conversation_id: int, viewer_username: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, conversation_type, title, created_by, metadata, created_at, last_message_at
            FROM dm_conversations
            WHERE id = ?
        """, (conversation_id,))
        conv_row = c.fetchone()
        if not conv_row:
            return None

        c.execute("""
            SELECT
                p.username,
                p.role,
                p.joined_at,
                p.left_at,
                p.last_read_message_id,
                p.last_read_at,
                p.last_active_at,
                COALESCE(profiles.display_name, p.username) AS display_name,
                profiles.avatar_url
            FROM dm_participants p
            LEFT JOIN profiles ON profiles.username = p.username
            WHERE p.conversation_id = ?
            ORDER BY p.joined_at ASC
        """, (conversation_id,))
        participant_rows = c.fetchall()

        c.execute("""
            SELECT
                m.id,
                m.conversation_id,
                m.sender_id,
                COALESCE(m.body, ''),
                COALESCE(m.message_type, 'text') AS message_type,
                m.created_at,
                COALESCE(profiles.display_name, m.sender_id) AS display_name,
                m.rich_content
            FROM dm_messages m
            LEFT JOIN profiles ON profiles.username = m.sender_id
            WHERE m.conversation_id = ?
              AND m.deleted_at IS NULL
            ORDER BY m.id DESC
            LIMIT 1
        """, (conversation_id,))
        last_message_row = c.fetchone()

        participants: List[Dict[str, Any]] = []
        viewer_state: Dict[str, Any] = {}
        for row in participant_rows:
            participant = {
                "username": row[0],
                "role": row[1],
                "joined_at": _to_datetime_string(row[2]),
                "left_at": _to_datetime_string(row[3]) if row[3] else None,
                "last_read_message_id": row[4],
                "last_read_at": _to_datetime_string(row[5]) if row[5] else None,
                "last_active_at": _to_datetime_string(row[6]) if row[6] else None,
                "display_name": row[7],
                "avatar_url": row[8],
            }
            participants.append(participant)
            if viewer_username and row[0] == viewer_username:
                viewer_state = dict(participant)

        metadata = _load_json(conv_row[4], {})
        if not isinstance(metadata, dict):
            metadata = {}

        title = _derive_dm_title(conv_row[1], participants, viewer_username, conv_row[2])

        last_message = _build_dm_message_from_row(last_message_row) if last_message_row else None
        if last_message:
            _attach_dm_reactions([last_message], viewer_username)

        unread_count = 0
        last_read_id = viewer_state.get("last_read_message_id") if viewer_state else None
        if viewer_username and any(p["username"] == viewer_username and not p["left_at"] for p in participants):
            if last_read_id:
                c.execute("""
                    SELECT COUNT(*)
                    FROM dm_messages
                    WHERE conversation_id = ?
                      AND deleted_at IS NULL
                      AND id > ?
                """, (conversation_id, last_read_id))
            else:
                c.execute("""
                    SELECT COUNT(*)
                    FROM dm_messages
                    WHERE conversation_id = ?
                      AND deleted_at IS NULL
                """, (conversation_id,))
            unread_count = c.fetchone()[0]

    return {
        "id": conv_row[0],
        "type": conv_row[1],
        "title": title,
        "created_by": conv_row[3],
        "metadata": metadata,
        "created_at": _to_datetime_string(conv_row[5]),
        "last_message_at": _to_datetime_string(conv_row[6]) if conv_row[6] else None,
        "participants": participants,
        "viewer_state": viewer_state,
        "last_message": last_message,
        "unread_count": unread_count,
    }


@log_errors()
def get_dm_messages(conversation_id: int, limit: int = 50,
                    after_id: Optional[int] = None,
                    before_id: Optional[int] = None,
                    viewer_username: Optional[str] = None) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 200))
    base_query = """
        SELECT
            m.id,
            m.conversation_id,
            m.sender_id,
            COALESCE(m.body, ''),
            COALESCE(m.message_type, 'text') AS message_type,
            m.created_at,
            COALESCE(profiles.display_name, m.sender_id) AS display_name,
            m.rich_content
        FROM dm_messages m
        LEFT JOIN profiles ON profiles.username = m.sender_id
        WHERE m.conversation_id = ?
          AND m.deleted_at IS NULL
    """
    params: List[Any] = [conversation_id]

    if after_id is not None:
        base_query += " AND m.id > ?"
        params.append(after_id)
    if before_id is not None:
        base_query += " AND m.id < ?"
        params.append(before_id)

    base_query += " ORDER BY m.id ASC LIMIT ?"
    params.append(limit)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(base_query, tuple(params))
        rows = c.fetchall()

    messages = [_build_dm_message_from_row(row) for row in rows]
    _attach_dm_reactions(messages, viewer_username)
    return messages


@log_errors()
def create_dm_message(conversation_id: int, sender_id: str, body: str,
                      message_type: str = "text", rich_content: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    log_event(
        "dm.message.attempt",
        conversation_id=conversation_id,
        sender_id=sender_id,
        message_type=message_type or "text",
    )
    allowed_types = {"text", "listing", "saved_search", "quick_reply", "attachment"}
    message_type = message_type or "text"
    if message_type not in allowed_types:
        raise ValueError("Unsupported message type")

    clean_body = (body or "").strip()
    if message_type == "text" and not clean_body:
        raise ValueError("Message cannot be empty")
    if len(clean_body) > 2000:
        raise ValueError("Message must be 2000 characters or fewer")

    if message_type != "text" and (not rich_content or not isinstance(rich_content, dict)):
        raise ValueError("Attachment payload required for non-text message")

    now = datetime.now()
    rich_payload = _dump_json(rich_content) if rich_content else None

    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()

            if not _is_active_dm_participant(c, conversation_id, sender_id):
                raise ValueError("User is not part of this conversation")

            c.execute("""
                SELECT username
                FROM dm_participants
                WHERE conversation_id = ?
                  AND (left_at IS NULL)
            """, (conversation_id,))
            participant_rows = c.fetchall()
            for row in participant_rows:
                participant_username = row[0]
                if participant_username == sender_id:
                    continue
                if _are_users_blocked(c, sender_id, participant_username):
                    raise ValueError("Cannot send messages to a user you have blocked.")

            try:
                c.execute("""
                    INSERT INTO dm_messages (conversation_id, sender_id, body, rich_content, message_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (conversation_id, sender_id, clean_body if clean_body else None, rich_payload, message_type, now))
                message_id = c.lastrowid

                c.execute("""
                    UPDATE dm_conversations
                    SET last_message_at = ?
                    WHERE id = ?
                """, (now, conversation_id))

                c.execute("""
                    UPDATE dm_participants
                    SET last_active_at = ?, last_read_message_id = ?, last_read_at = ?
                    WHERE conversation_id = ? AND username = ? AND (left_at IS NULL)
                """, (now, message_id, now, conversation_id, sender_id))

                conn.commit()
                log_event(
                    "dm.message.created",
                    conversation_id=conversation_id,
                    message_id=message_id,
                    sender_id=sender_id,
                    message_type=message_type,
                    recipient_count=len(participant_rows) - 1 if participant_rows else 0,
                )
            except Exception:
                conn.rollback()
                raise
    except Exception as exc:
        log_alert(
            "dm.message.failed",
            "Failed to create DM message",
            severity="error",
            conversation_id=conversation_id,
            sender_id=sender_id,
            message_type=message_type,
            error=str(exc),
        )
        raise

    try:
        log_profile_activity(
            sender_id,
            "dm_message_sent",
            entity_id=str(conversation_id),
            metadata={"message_id": message_id, "type": message_type},
            visibility="connections",
        )
    except Exception:
        pass

    recent = get_dm_messages(
        conversation_id,
        limit=1,
        after_id=message_id - 1 if message_id else None,
        viewer_username=sender_id,
    )
    if recent:
        message_record = recent[0]
    else:
        message_record = {
            "id": message_id,
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "body": clean_body,
            "message_type": message_type,
            "created_at": _to_datetime_string(now),
            "display_name": sender_id,
            "rich_content": rich_content or {},
        }

    try:
        participants = list_dm_participants(conversation_id)
        recipients = [
            participant for participant in participants
            if participant.get("username")
            and participant["username"] != sender_id
            and not participant.get("left_at")
        ]
        if recipients:
            snippet_source = (message_record.get("body") or "").strip()
            rich_preview = message_record.get("rich_content") or {}
            if not snippet_source and isinstance(rich_preview, dict):
                snippet_source = str(
                    rich_preview.get("title")
                    or rich_preview.get("body")
                    or rich_preview.get("summary")
                    or ""
                ).strip()
            if not snippet_source:
                snippet_source = message_type.replace("_", " ").title()
            snippet = snippet_source
            if len(snippet) > 160:
                snippet = snippet[:157] + "…"

            base_payload = {
                "conversation_id": conversation_id,
                "message_id": message_record.get("id"),
                "sender": sender_id,
                "sender_display": message_record.get("display_name") or sender_id,
                "preview": snippet,
                "created_at": message_record.get("created_at"),
                "message_type": message_type,
            }
            if rich_preview:
                base_payload["rich_content"] = rich_preview

            for recipient in recipients:
                username = recipient["username"]
                payload = dict(base_payload)
                payload["recipient"] = {
                    "username": username,
                    "display_name": recipient.get("display_name") or username,
                }
                try:
                    event = log_feed_event(
                        event_type="dm_message",
                        actor_username=sender_id,
                        entity_type="dm_message",
                        entity_id=str(message_record.get("id")),
                        audience_type="user",
                        audience_id=username,
                        target_username=username,
                        payload=payload,
                        score=6.0,
                    )
                except Exception as feed_exc:
                    logger.warning(f"Failed to log DM feed event for {conversation_id}: {feed_exc}")
                    event = None

                try:
                    create_notification(
                        username,
                        "dm_message",
                        payload=payload,
                        event_id=event["id"] if isinstance(event, dict) else None,
                    )
                except Exception as notif_exc:
                    logger.warning(f"Failed to enqueue DM notification for {username}: {notif_exc}")
    except Exception as exc:
        logger.warning(f"Failed to build DM feed payload for conversation {conversation_id}: {exc}")

    return message_record


@log_errors()
def update_dm_read_receipt(conversation_id: int, username: str, message_id: int) -> bool:
    if message_id is None:
        return False

    now = datetime.now()
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT last_read_message_id
            FROM dm_participants
            WHERE conversation_id = ?
              AND username = ?
              AND (left_at IS NULL)
        """, (conversation_id, username))
        row = c.fetchone()
        if not row:
            return False

        current_last_read = row[0] or 0
        if current_last_read and current_last_read >= message_id:
            c.execute("""
                UPDATE dm_participants
                SET last_read_at = ?, last_active_at = ?
                WHERE conversation_id = ? AND username = ? AND (left_at IS NULL)
            """, (now, now, conversation_id, username))
        else:
            c.execute("""
                UPDATE dm_participants
                SET last_read_message_id = ?, last_read_at = ?, last_active_at = ?
                WHERE conversation_id = ? AND username = ? AND (left_at IS NULL)
            """, (message_id, now, now, conversation_id, username))
        conn.commit()
    return True


@log_errors()
def mark_dm_participant_active(conversation_id: int, username: str) -> None:
    now = datetime.now()
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE dm_participants
            SET last_active_at = ?
            WHERE conversation_id = ? AND username = ? AND (left_at IS NULL)
        """, (now, conversation_id, username))
        conn.commit()
@log_errors()
def list_dm_participants(conversation_id: int) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                p.username,
                p.role,
                p.joined_at,
                p.left_at,
                p.last_read_message_id,
                p.last_read_at,
                p.last_active_at,
                COALESCE(profiles.display_name, p.username) AS display_name,
                profiles.avatar_url
            FROM dm_participants p
            LEFT JOIN profiles ON profiles.username = p.username
            WHERE p.conversation_id = ?
        """, (conversation_id,))
        rows = c.fetchall()

    participants: List[Dict[str, Any]] = []
    for row in rows:
        participants.append({
            "username": row[0],
            "role": row[1],
            "joined_at": _to_datetime_string(row[2]),
            "left_at": _to_datetime_string(row[3]) if row[3] else None,
            "last_read_message_id": row[4],
            "last_read_at": _to_datetime_string(row[5]) if row[5] else None,
            "last_active_at": _to_datetime_string(row[6]) if row[6] else None,
            "display_name": row[7],
            "avatar_url": row[8],
        })
    return participants


def _fetch_dm_reaction_map(message_ids: Sequence[int], viewer_username: Optional[str]) -> Dict[int, List[Dict[str, Any]]]:
    if not message_ids:
        return {}

    placeholders = ",".join("?" for _ in message_ids)
    params: List[Any]

    if viewer_username:
        params = [viewer_username, *message_ids]
        query = f"""
            SELECT message_id,
                   reaction_type,
                   COUNT(*) AS total_count,
                   SUM(CASE WHEN username = ? THEN 1 ELSE 0 END) AS viewer_count
            FROM dm_message_reactions
            WHERE message_id IN ({placeholders})
            GROUP BY message_id, reaction_type
        """
    else:
        params = list(message_ids)
        query = f"""
            SELECT message_id,
                   reaction_type,
                   COUNT(*) AS total_count,
                   0 AS viewer_count
            FROM dm_message_reactions
            WHERE message_id IN ({placeholders})
            GROUP BY message_id, reaction_type
        """

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(query, tuple(params))
        rows = c.fetchall()

    reaction_map: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        reaction_list = reaction_map.setdefault(row[0], [])
        reaction_list.append({
            "reaction": row[1],
            "count": row[2],
            "viewer_reacted": bool(row[3]),
        })
    return reaction_map


def _attach_dm_reactions(messages: Sequence[Dict[str, Any]], viewer_username: Optional[str]) -> None:
    message_ids = [message.get("id") for message in messages if message.get("id")]
    if not message_ids:
        return
    reaction_map = _fetch_dm_reaction_map(message_ids, viewer_username)
    for message in messages:
        message["reactions"] = reaction_map.get(message.get("id"), [])


@log_errors()
def get_dm_reactions(message_id: int, viewer_username: Optional[str] = None) -> List[Dict[str, Any]]:
    reaction_map = _fetch_dm_reaction_map([message_id], viewer_username)
    return reaction_map.get(message_id, [])
@log_errors()
def add_dm_message_reaction(message_id: int, username: str, reaction_type: str) -> List[Dict[str, Any]]:
    reaction = (reaction_type or "").strip()
    if not reaction:
        raise ValueError("Reaction type is required")
    if len(reaction) > 32:
        raise ValueError("Reaction must be 32 characters or fewer")

    now = datetime.now()
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT OR IGNORE INTO dm_message_reactions (message_id, username, reaction_type, created_at)
            VALUES (?, ?, ?, ?)
        """, (message_id, username, reaction, now))
        conn.commit()

    return get_dm_reactions(message_id, username)


@log_errors()
def remove_dm_message_reaction(message_id: int, username: str, reaction_type: str) -> List[Dict[str, Any]]:
    reaction = (reaction_type or "").strip()
    if not reaction:
        raise ValueError("Reaction type is required")

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM dm_message_reactions
            WHERE message_id = ?
              AND username = ?
              AND reaction_type = ?
        """, (message_id, username, reaction))
        conn.commit()

    return get_dm_reactions(message_id, username)
def _serialize_invite_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    expires_at_dt = _parse_db_datetime(row[4])
    max_uses = row[5]
    uses = row[6] or 0
    metadata = _load_json(row[7], {})
    return {
        "id": row[0],
        "server_id": row[1],
        "created_by": row[2],
        "code": row[3],
        "expires_at": _to_datetime_string(expires_at_dt),
        "max_uses": max_uses,
        "uses": uses,
        "metadata": metadata if isinstance(metadata, dict) else {},
        "created_at": _to_datetime_string(row[8]),
        "expired": bool(expires_at_dt and expires_at_dt < datetime.now()),
        "remaining_uses": None if max_uses in (None, 0) else max(max_uses - uses, 0),
    }
def _get_invite_for_update(cursor, server_id: int, code: str) -> Optional[Tuple[Any, ...]]:
    cursor.execute("""
        SELECT id, server_id, created_by, code, expires_at, max_uses, uses, metadata, created_at
        FROM server_invites
        WHERE server_id = ? AND code = ?
    """, (server_id, code))
    row = cursor.fetchone()
    if not row:
        return None

    expires_at_dt = _parse_db_datetime(row[4])
    if expires_at_dt and expires_at_dt < datetime.now():
        return None

    max_uses = row[5]
    uses = row[6] or 0
    if max_uses not in (None, 0) and uses >= max_uses:
        return None
    return row


def _run_server_search(
    cursor,
    query: Optional[str],
    tags: Optional[List[str]],
    limit: int,
    offset: int = 0,
    *,
    include_non_public: bool = False,
    order: str = "popularity",
    location: Optional[str] = None,
    min_members: Optional[int] = None,
) -> List[Dict[str, Any]]:
    conditions: List[str] = []
    if not include_non_public:
        conditions.append("s.visibility = 'public'")
    params: List[Any] = []

    if query:
        normalized_query = f"%{query.lower()}%"
        conditions.append("(LOWER(s.name) LIKE ? OR LOWER(s.description) LIKE ?)")
        params.extend([normalized_query, normalized_query])

    if tags:
        for tag in tags[:SERVER_TOPIC_TAG_LIMIT]:
            slug = _slugify(tag, fallback="tag")
            conditions.append("s.topic_tags LIKE ?")
            params.append(f'%\"slug\": \"{slug}\"%')

    if location:
        normalized_location = f"%{location.lower()}%"
        conditions.append("LOWER(COALESCE(s.settings, '')) LIKE ?")
        params.append(normalized_location)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    if order == "name":
        order_clause = "ORDER BY LOWER(s.name) ASC"
    elif order == "new":
        order_clause = "ORDER BY s.created_at DESC"
    else:
        order_clause = "ORDER BY sb.expires_at DESC NULLS LAST, s.created_at DESC"

    cursor.execute(f"""
        SELECT
            s.id,
            s.owner_username,
            s.name,
            s.slug,
            s.description,
            s.topic_tags,
            s.visibility,
            s.icon_url,
            s.banner_url,
            s.settings,
            s.created_at,
            s.updated_at,
            COALESCE(active_counts.active_members, 0) AS member_count,
            COALESCE(pending_counts.pending_members, 0) AS pending_count,
            COALESCE(sb.status, '') AS boost_status,
            sb.expires_at AS boost_expires,
            sb.metadata AS boost_metadata
        FROM servers s
        LEFT JOIN (
            SELECT server_id, COUNT(*) AS active_members
            FROM server_memberships
            WHERE status = 'active'
            GROUP BY server_id
        ) AS active_counts ON active_counts.server_id = s.id
        LEFT JOIN (
            SELECT server_id, COUNT(*) AS pending_members
            FROM server_memberships
            WHERE status = 'pending'
            GROUP BY server_id
        ) AS pending_counts ON pending_counts.server_id = s.id
        LEFT JOIN server_boosts sb
          ON sb.server_id = s.id
         AND sb.status = 'active'
         AND (sb.expires_at IS NULL OR sb.expires_at >= CURRENT_TIMESTAMP)
        WHERE {where_clause}
        {order_clause}
        LIMIT ? OFFSET ?
    """, tuple(params + [limit, offset]))

    rows = cursor.fetchall()
    results: List[Dict[str, Any]] = []
    for row in rows:
        server = _server_row_to_dict(row)
        if len(row) > 12:
            server["member_count"] = row[12] or 0
        if len(row) > 13:
            server["pending_requests"] = row[13] or 0
        if len(row) > 14:
            server["boost_status"] = row[14] or ""
        if len(row) > 15:
            server["boost_expires"] = _to_datetime_string(row[15]) if row[15] else None
        if len(row) > 16:
            server["boost_metadata"] = _load_json(row[16], {})
        if min_members is not None and server.get("member_count", 0) < int(min_members):
            continue
        results.append(server)
    return results


def _count_server_search(
    cursor,
    query: Optional[str],
    tags: Optional[List[str]],
    *,
    include_non_public: bool = False,
    location: Optional[str] = None,
    min_members: Optional[int] = None,
) -> int:
    conditions: List[str] = []
    params: List[Any] = []
    if not include_non_public:
        conditions.append("visibility = 'public'")

    if query:
        normalized_query = f"%{query.lower()}%"
        conditions.append("(LOWER(name) LIKE ? OR LOWER(description) LIKE ?)")
        params.extend([normalized_query, normalized_query])

    if tags:
        for tag in tags[:SERVER_TOPIC_TAG_LIMIT]:
            slug = _slugify(tag, fallback="tag")
            conditions.append("topic_tags LIKE ?")
            params.append(f'%\"slug\": \"{slug}\"%')

    if location:
        normalized_location = f"%{location.lower()}%"
        conditions.append("LOWER(COALESCE(settings, '')) LIKE ?")
        params.append(normalized_location)

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    cursor.execute(f"""
        SELECT COUNT(*)
        FROM (
            SELECT s.id,
                   COALESCE(active_counts.active_members, 0) AS member_count
            FROM servers s
            LEFT JOIN (
                SELECT server_id, COUNT(*) AS active_members
                FROM server_memberships
                WHERE status = 'active'
                GROUP BY server_id
            ) AS active_counts ON active_counts.server_id = s.id
            WHERE {where_clause}
        ) AS scoped
        WHERE (? IS NULL OR member_count >= ?)
    """, tuple(params + ([min_members, min_members] if min_members is not None else [None, None])))
    row = cursor.fetchone()
    return int(row[0]) if row else 0


def _annotate_discovery_score(server: Dict[str, Any]) -> None:
    member_count = int(server.get("member_count") or 0)
    pending = int(server.get("pending_requests") or 0)
    created_at = _parse_db_datetime(server.get("created_at"))
    age_days: Optional[float] = None
    if created_at:
        age_days = max((datetime.now() - created_at).total_seconds() / 86400.0, 0.0)
    recency_boost = 0.0
    if age_days is not None:
        if age_days < 1:
            recency_boost = 8.0
        elif age_days < 7:
            recency_boost = max(0.0, 8.0 - age_days)
        elif age_days < 30:
            recency_boost = max(0.0, 4.0 - (age_days - 7) * 0.2)
    score = member_count * 1.0 + pending * 0.3 + recency_boost
    server["discovery_score"] = round(score, 3)
    server["is_new"] = bool(age_days is not None and age_days <= 7)
@log_errors()
def create_server(owner_username: str,
                  name: str,
                  description: Optional[str] = None,
                  topic_tags: Optional[Any] = None,
                  visibility: Optional[str] = None,
                  icon_url: Optional[str] = None,
                  banner_url: Optional[str] = None,
                  settings: Optional[Dict[str, Any]] = None,
                  slug: Optional[str] = None) -> Dict[str, Any]:
    if not name or not isinstance(name, str):
        raise ValueError("Server name is required")

    cleaned_name = name.strip()
    if len(cleaned_name) < 3:
        raise ValueError("Server name must be at least 3 characters")
    if len(cleaned_name) > SERVER_NAME_MAX_LENGTH:
        cleaned_name = cleaned_name[:SERVER_NAME_MAX_LENGTH]

    cleaned_description = (description or "").strip() or None
    if cleaned_description and len(cleaned_description) > SERVER_DESCRIPTION_MAX_LENGTH:
        cleaned_description = cleaned_description[:SERVER_DESCRIPTION_MAX_LENGTH]

    normalized_visibility = (visibility or SERVER_DEFAULT_VISIBILITY).lower()
    if normalized_visibility not in SERVER_VISIBILITY_OPTIONS:
        normalized_visibility = SERVER_DEFAULT_VISIBILITY

    normalized_tags = _normalize_topic_tags(topic_tags)
    slug_value = _generate_unique_server_slug(cleaned_name, slug)
    settings_payload = settings if isinstance(settings, dict) else {}
    timestamp = datetime.now()

    with get_pool().get_connection() as conn:
        try:
            conn.execute("BEGIN")
        except Exception:
            pass
        c = conn.cursor()
        try:
            c.execute("""
                INSERT INTO servers (
                    owner_username,
                    name,
                    slug,
                    description,
                    topic_tags,
                    visibility,
                    icon_url,
                    banner_url,
                    settings,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                owner_username,
                cleaned_name,
                slug_value,
                cleaned_description,
                _dump_json(normalized_tags),
                normalized_visibility,
                icon_url,
                banner_url,
                _dump_json(settings_payload),
                timestamp,
                timestamp,
            ))
            server_id = c.lastrowid

            role_ids = _bootstrap_server_roles(c, server_id, timestamp)
            _bootstrap_server_channels(c, server_id, timestamp)

            owner_role_id = role_ids.get("owner")
            c.execute("""
                INSERT INTO server_memberships (
                    server_id,
                    username,
                    role_id,
                    status,
                    invited_by,
                    invite_code,
                    requested_at,
                    joined_at,
                    last_active_at,
                    reviewed_at,
                    reviewed_by
                ) VALUES (?, ?, ?, 'active', ?, NULL, ?, ?, ?, ?, ?)
            """, (
                server_id,
                owner_username,
                owner_role_id,
                owner_username,
                timestamp,
                timestamp,
                timestamp,
                timestamp,
                owner_username,
            ))

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    server = get_server_by_id(server_id, viewer_username=owner_username, include_channels=True, include_roles=True)
    logger.info(f"Created new community server '{slug_value}' (ID: {server_id}) owned by {owner_username}")
    return server


@log_errors()
def get_server_by_id(server_id: int,
                     viewer_username: Optional[str] = None,
                     include_channels: bool = False,
                     include_roles: bool = False) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, owner_username, name, slug, description, topic_tags, visibility, icon_url, banner_url, settings, created_at, updated_at
            FROM servers
            WHERE id = ?
        """, (server_id,))
        row = c.fetchone()
        if not row:
            return None
        return _compose_server_payload(c, row, viewer_username, include_channels, include_roles)


@log_errors()
def get_server_by_slug(slug: str,
                       viewer_username: Optional[str] = None,
                       include_channels: bool = False,
                       include_roles: bool = False) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, owner_username, name, slug, description, topic_tags, visibility, icon_url, banner_url, settings, created_at, updated_at
            FROM servers
            WHERE slug = ?
        """, (slug,))
        row = c.fetchone()
        if not row:
            return None
        return _compose_server_payload(c, row, viewer_username, include_channels, include_roles)


@log_errors()
def get_server_channels(server_id: int) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        return _get_server_channels_with_cursor(c, server_id)


@log_errors()
def create_server_channel(server_id: int,
                          name: str,
                          channel_type: str = "text",
                          topic: Optional[str] = None,
                          position: Optional[int] = None,
                          settings: Optional[Dict[str, Any]] = None,
                          created_by: Optional[str] = None) -> Dict[str, Any]:
    if channel_type not in SERVER_CHANNEL_TYPES:
        raise ValueError(f"Unsupported channel type: {channel_type}")
    if not name or not isinstance(name, str):
        raise ValueError("Channel name is required")

    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("Channel name cannot be empty")

    timestamp = datetime.now()

    with get_pool().get_connection() as conn:
        try:
            conn.execute("BEGIN")
        except Exception:
            pass
        c = conn.cursor()
        try:
            slug_value = _generate_channel_slug(c, server_id, cleaned_name)
            if position is None:
                c.execute("""
                    SELECT COALESCE(MAX(position), 0)
                    FROM server_channels
                    WHERE server_id = ?
                """, (server_id,))
                max_position = c.fetchone()[0] or 0
                channel_position = max_position + 1
            else:
                channel_position = position

            c.execute("""
                INSERT INTO server_channels (
                    server_id,
                    channel_type,
                    name,
                    slug,
                    topic,
                    position,
                    settings,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                server_id,
                channel_type,
                cleaned_name,
                slug_value,
                (topic or "").strip() or None,
                channel_position,
                _dump_json(settings or {}),
                timestamp,
                timestamp,
            ))
            channel_id = c.lastrowid
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, server_id, channel_type, name, slug, topic, position, settings, created_at, updated_at
            FROM server_channels
            WHERE id = ?
        """, (channel_id,))
        row = c.fetchone()
    return _channel_row_to_dict(row)


@log_errors()
def get_server_roles(server_id: int) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        return _get_server_roles_with_cursor(c, server_id)


@log_errors()
def get_server_membership(server_id: int,
                          username: str,
                          include_permissions: bool = False) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        return _get_membership_with_cursor(c, server_id, username, include_permissions=include_permissions)


def _get_server_settings(server_id: int) -> Dict[str, Any]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT settings
            FROM servers
            WHERE id = ?
        """, (server_id,))
        row = c.fetchone()
    if not row:
        raise ValueError("Server not found")
    settings = _load_json(row[0], {})
    return settings if isinstance(settings, dict) else {}


def _persist_server_settings(server_id: int, settings: Dict[str, Any]) -> None:
    timestamp = datetime.now()
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE servers
            SET settings = ?,
                updated_at = ?
            WHERE id = ?
        """, (_dump_json(settings), timestamp, server_id))
        if c.rowcount == 0:
            raise ValueError("Server not found")
        conn.commit()


def _normalize_keyword_filter_entry(entry: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(entry, dict):
        return None
    phrase = str(entry.get("phrase") or "").strip()
    if not phrase:
        return None
    if len(phrase) > KEYWORD_FILTER_MAX_PHRASE_LENGTH:
        phrase = phrase[:KEYWORD_FILTER_MAX_PHRASE_LENGTH]
    action = (entry.get("action") or "block").strip().lower()
    if action not in KEYWORD_FILTER_ALLOWED_ACTIONS:
        action = "block"
    normalized: Dict[str, Any] = {
        "phrase": phrase,
        "action": action,
    }
    for optional_key in ("created_at", "created_by", "updated_at", "updated_by", "notes"):
        if optional_key in entry and entry[optional_key] is not None:
            normalized[optional_key] = entry[optional_key]
    return normalized


@log_errors()
def get_server_keyword_filters(server_id: int) -> List[Dict[str, Any]]:
    settings = _get_server_settings(server_id)
    raw_filters = settings.get("keyword_filters", [])
    if not isinstance(raw_filters, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for entry in raw_filters:
        normalized_entry = _normalize_keyword_filter_entry(entry)
        if normalized_entry:
            normalized.append(normalized_entry)
    normalized.sort(key=lambda item: item["phrase"].lower())
    return deepcopy(normalized)


@log_errors()
def add_server_keyword_filter(server_id: int,
                              phrase: str,
                              action: str,
                              *,
                              created_by: Optional[str] = None) -> List[Dict[str, Any]]:
    normalized = _normalize_keyword_filter_entry({"phrase": phrase, "action": action})
    if not normalized:
        raise ValueError("phrase is required")

    now = _to_datetime_string(datetime.now())
    settings = _get_server_settings(server_id)
    current_filters = settings.get("keyword_filters")
    existing: List[Dict[str, Any]] = []
    if isinstance(current_filters, list):
        for entry in current_filters:
            normalized_entry = _normalize_keyword_filter_entry(entry)
            if normalized_entry:
                existing.append(normalized_entry)

    target_phrase = normalized["phrase"].lower()
    updated = False
    for idx, entry in enumerate(existing):
        if entry["phrase"].lower() == target_phrase:
            entry["action"] = normalized["action"]
            entry["updated_at"] = now
            if created_by:
                entry["updated_by"] = created_by
            existing[idx] = entry
            updated = True
            break

    if not updated:
        normalized["created_at"] = now
        if created_by:
            normalized["created_by"] = created_by
        existing.append(normalized)

    existing.sort(key=lambda item: item["phrase"].lower())
    settings["keyword_filters"] = existing
    _persist_server_settings(server_id, settings)
    return deepcopy(existing)


@log_errors()
def remove_server_keyword_filter(server_id: int, phrase: str) -> List[Dict[str, Any]]:
    normalized_phrase = (phrase or "").strip()
    if not normalized_phrase:
        raise ValueError("phrase is required")
    target = normalized_phrase.lower()

    settings = _get_server_settings(server_id)
    current_filters = settings.get("keyword_filters")
    remaining: List[Dict[str, Any]] = []
    removed = False
    if isinstance(current_filters, list):
        for entry in current_filters:
            normalized_entry = _normalize_keyword_filter_entry(entry)
            if not normalized_entry:
                continue
            if normalized_entry["phrase"].lower() == target:
                removed = True
                continue
            remaining.append(normalized_entry)

    if not removed:
        raise ValueError("Keyword filter not found")

    remaining.sort(key=lambda item: item["phrase"].lower())
    settings["keyword_filters"] = remaining
    _persist_server_settings(server_id, settings)
    return deepcopy(remaining)


@log_errors()
def get_user_server_permissions(server_id: int, username: str) -> Dict[str, bool]:
    membership = get_server_membership(server_id, username, include_permissions=True)
    if not membership or membership.get("status") != "active":
        return {}
    permissions = membership.get("permissions") or {}
    if not isinstance(permissions, dict):
        return {}
    return permissions


@log_errors()
def get_server_invite_by_code(code: str) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, server_id, created_by, code, expires_at, max_uses, uses, metadata, created_at
            FROM server_invites
            WHERE code = ?
        """, (code,))
        row = c.fetchone()
        if not row:
            return None
    return _serialize_invite_row(row)
@log_errors()
def create_server_invite(server_id: int,
                         created_by: str,
                         expires_in_hours: Optional[int] = None,
                         max_uses: Optional[int] = None,
                         metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with get_pool().get_connection() as conn:
        try:
            conn.execute("BEGIN")
        except Exception:
            pass
        c = conn.cursor()
        try:
            membership = _get_membership_with_cursor(c, server_id, created_by, include_permissions=True)
            if not membership or membership.get("status") != "active":
                raise PermissionError("Only active members may create invites")

            permissions = membership.get("permissions") or {}
            is_owner = membership.get("role_name", "").lower() == "owner"
            if not (is_owner or permissions.get("manage_invites") or permissions.get("manage_server")):
                raise PermissionError("Insufficient permissions to create invites")

            code = _generate_invite_code()
            while True:
                c.execute("SELECT 1 FROM server_invites WHERE code = ?", (code,))
                if not c.fetchone():
                    break
                code = _generate_invite_code()

            expires_at = None
            if expires_in_hours:
                try:
                    expires_in = int(expires_in_hours)
                    if expires_in > 0:
                        expires_at = datetime.now() + timedelta(hours=expires_in)
                except (TypeError, ValueError):
                    pass

            c.execute("""
                INSERT INTO server_invites (
                    server_id,
                    created_by,
                    code,
                    expires_at,
                    max_uses,
                    uses,
                    metadata,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """, (
                server_id,
                created_by,
                code,
                expires_at,
                max_uses,
                _dump_json(metadata or {}),
                datetime.now(),
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    invite = get_server_invite_by_code(code)
    if invite:
        logger.info(f"Created invite {invite['code']} for server {server_id} by {created_by}")
    return invite
@log_errors()
def join_server(slug: str,
                username: str,
                invite_code: Optional[str] = None) -> Dict[str, Any]:
    log_event(
        "server.join.attempt",
        server_slug=slug,
        username=username,
        has_invite=bool(invite_code),
    )
    with get_pool().get_connection() as conn:
        try:
            conn.execute("BEGIN")
        except Exception:
            pass
        c = conn.cursor()
        try:
            c.execute("""
                SELECT id, owner_username, name, slug, description, topic_tags, visibility, icon_url, banner_url, settings, created_at, updated_at
                FROM servers
                WHERE slug = ?
            """, (slug,))
            server_row = c.fetchone()
            if not server_row:
                raise ValueError("Server not found")

            server_id = server_row[0]
            visibility = server_row[6] or SERVER_DEFAULT_VISIBILITY

            existing_membership = _get_membership_with_cursor(c, server_id, username, include_permissions=True)
            if existing_membership:
                if existing_membership["status"] == "banned":
                    raise PermissionError("You are banned from this server")
                return {
                    "server": _compose_server_payload(c, server_row, username, include_channels=False, include_roles=False),
                    "membership": existing_membership,
                    "status": existing_membership["status"],
                    "activated": existing_membership["status"] == "active",
                    "already_member": True,
                }

            invite_row = None
            if invite_code:
                invite_row = _get_invite_for_update(c, server_id, invite_code)
                if not invite_row:
                    raise ValueError("Invite code is invalid or expired")

            status = "active" if visibility == "public" or invite_row else "pending"
            now = datetime.now()
            default_role_id = _get_default_role_id(c, server_id)

            c.execute("""
                INSERT INTO server_memberships (
                    server_id,
                    username,
                    role_id,
                    status,
                    invited_by,
                    invite_code,
                    requested_at,
                    joined_at,
                    last_active_at,
                    reviewed_at,
                    reviewed_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                server_id,
                username,
                default_role_id,
                status,
                invite_row[2] if invite_row else None,
                invite_row[3] if invite_row else None,
                now,
                now if status == "active" else None,
                now if status == "active" else None,
                None,
                None,
            ))

            if invite_row:
                c.execute("""
                    UPDATE server_invites
                    SET uses = uses + 1
                    WHERE id = ?
                """, (invite_row[0],))

            conn.commit()
            log_event(
                "server.join.commit",
                server_id=server_id,
                server_slug=slug,
                username=username,
                status=status,
                invite_used=bool(invite_row),
            )
        except Exception:
            conn.rollback()
            log_alert(
                "server.join.failed",
                "Failed to join server",
                severity="error",
                server_slug=slug,
                username=username,
                has_invite=bool(invite_code),
            )
            raise

    membership = get_server_membership(server_id, username, include_permissions=True)
    server = get_server_by_id(server_id, viewer_username=username, include_channels=True, include_roles=False)
    return {
        "server": server,
        "membership": membership,
        "status": membership["status"] if membership else status,
        "activated": membership["status"] == "active" if membership else False,
        "already_member": False,
    }
def list_server_pending_requests(server_id: int,
                                 actor_username: str,
                                 limit: int = 50) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        actor_membership = _get_membership_with_cursor(c, server_id, actor_username, include_permissions=True)
        if not actor_membership or actor_membership.get("status") != "active":
            raise PermissionError("Only active members may view requests")

        permissions = actor_membership.get("permissions") or {}
        is_owner = actor_membership.get("role_name", "").lower() == "owner"
        if not (is_owner or permissions.get("moderate_members") or permissions.get("manage_server")):
            raise PermissionError("Insufficient permissions to view join requests")

        c.execute("""
            SELECT m.server_id, m.username, m.role_id, m.status, m.invited_by, m.invite_code,
                   m.requested_at, m.joined_at, m.last_active_at, m.reviewed_at, m.reviewed_by,
                   r.name, r.permissions
            FROM server_memberships m
            LEFT JOIN server_roles r ON r.id = m.role_id
            WHERE m.server_id = ? AND m.status = 'pending'
            ORDER BY m.requested_at ASC
            LIMIT ?
        """, (server_id, limit))
        rows = c.fetchall()
    return [_serialize_membership_row(row) for row in rows]


@log_errors()
def respond_to_join_request(server_id: int,
                             actor_username: str,
                             target_username: str,
                             approve: bool) -> Dict[str, Any]:
    with get_pool().get_connection() as conn:
        try:
            conn.execute("BEGIN")
        except Exception:
            pass
        c = conn.cursor()
        try:
            actor_membership = _get_membership_with_cursor(c, server_id, actor_username, include_permissions=True)
            if not actor_membership or actor_membership.get("status") != "active":
                raise PermissionError("Only active members may review requests")

            permissions = actor_membership.get("permissions") or {}
            is_owner = actor_membership.get("role_name", "").lower() == "owner"
            if not (is_owner or permissions.get("moderate_members") or permissions.get("manage_server")):
                raise PermissionError("Insufficient permissions to review requests")

            target_membership = _get_membership_with_cursor(c, server_id, target_username, include_permissions=True)
            if not target_membership or target_membership.get("status") != "pending":
                raise ValueError("Join request not found or already processed")

            now = datetime.now()
            if approve:
                default_role_id = target_membership.get("role_id") or _get_default_role_id(c, server_id)
                c.execute("""
                    UPDATE server_memberships
                    SET status = 'active',
                        role_id = COALESCE(role_id, ?),
                        joined_at = COALESCE(joined_at, ?),
                        last_active_at = COALESCE(last_active_at, ?),
                        reviewed_at = ?,
                        reviewed_by = ?
                    WHERE server_id = ? AND username = ?
                """, (
                    default_role_id,
                    now,
                    now,
                    now,
                    actor_username,
                    server_id,
                    target_username,
                ))
                status = "active"
            else:
                c.execute("""
                    UPDATE server_memberships
                    SET status = 'rejected',
                        reviewed_at = ?,
                        reviewed_by = ?
                    WHERE server_id = ? AND username = ?
                """, (
                    now,
                    actor_username,
                    server_id,
                    target_username,
                ))
                status = "rejected"

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    membership = get_server_membership(server_id, target_username, include_permissions=True)
    return {
        "status": status,
        "membership": membership,
    }


@log_errors()
def list_user_servers(username: str,
                       status_filter: Optional[str] = "active",
                       limit: int = 100) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        params: List[Any] = [username]
        where_clause = "WHERE m.username = ?"
        if status_filter:
            where_clause += " AND m.status = ?"
            params.append(status_filter)

        params.append(limit)
        c.execute(f"""
            SELECT
                s.id,
                s.owner_username,
                s.name,
                s.slug,
                s.description,
                s.topic_tags,
                s.visibility,
                s.icon_url,
                s.banner_url,
                s.settings,
                s.created_at,
                s.updated_at,
                m.status,
                m.role_id,
                r.name
            FROM server_memberships m
            JOIN servers s ON s.id = m.server_id
            LEFT JOIN server_roles r ON r.id = m.role_id
            {where_clause}
            ORDER BY s.name ASC
            LIMIT ?
        """, tuple(params))
        rows = c.fetchall()

    servers: List[Dict[str, Any]] = []
    for row in rows:
        server = _server_row_to_dict(row)
        server["membership_status"] = row[12]
        server["role_id"] = row[13]
        server["role_name"] = row[14]
        servers.append(server)
    return servers


@log_errors()
def discover_servers(
    viewer_username: Optional[str] = None,
    query: Optional[str] = None,
    tags: Optional[List[str]] = None,
    limit: int = 20,
    offset: int = 0,
    *,
    location: Optional[str] = None,
    min_members: Optional[int] = None,
    order: str = "popularity",
) -> Dict[str, Any]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        results = _run_server_search(
            c,
            query,
            tags,
            limit,
            offset,
            include_non_public=False,
            order=order,
            location=location,
            min_members=min_members,
        )
        total = _count_server_search(
            c,
            query,
            tags,
            include_non_public=False,
            location=location,
            min_members=min_members,
        )

    user_memberships = list_user_servers(viewer_username, status_filter="active") if viewer_username else []
    member_slugs = {server["slug"] for server in user_memberships}

    trending = get_trending_servers(limit=6, location=location)
    recommended = get_recommended_servers(viewer_username, limit=6, location=location) if viewer_username else []

    def _dedupe(items: List[Dict[str, Any]], seen: set[str]) -> List[Dict[str, Any]]:
        filtered: List[Dict[str, Any]] = []
        for item in items:
            slug_value = item.get("slug")
            if not slug_value or slug_value in seen:
                continue
            seen.add(slug_value)
            filtered.append(item)
        return filtered

    seen_slugs = set(member_slugs)
    curated_results = _dedupe(results, seen_slugs.copy())
    curated_trending = _dedupe(trending, seen_slugs.copy())
    curated_recommended = _dedupe(recommended, seen_slugs.copy())

    for server in curated_results:
        _annotate_discovery_score(server)
    for collection in (curated_trending, curated_recommended):
        for server in collection:
            _annotate_discovery_score(server)

    if viewer_username:
        viewer_profile = get_profile(viewer_username)
        interest_slugs = _extract_interest_slugs_from_profile(viewer_profile)
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            combined_servers = curated_results + curated_trending + curated_recommended
            _enrich_servers_for_viewer(
                c,
                viewer_username,
                combined_servers,
                interest_slugs=interest_slugs,
                viewer_memberships=user_memberships,
            )
        sort_key = lambda srv: srv.get("personalized_score", srv.get("discovery_score", 0.0))
        curated_results.sort(key=sort_key, reverse=True)
        curated_recommended.sort(key=sort_key, reverse=True)

    return {
        "results": curated_results,
        "trending": curated_trending,
        "recommended": curated_recommended,
        "joined": user_memberships,
        "meta": {
            "limit": limit,
            "offset": offset,
            "total": total,
            "order": order,
            "location": location,
            "min_members": min_members,
        },
    }


@log_errors()
def search_servers(query: Optional[str] = None,
                    tags: Optional[List[str]] = None,
                    limit: int = 20,
                    offset: int = 0) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        return _run_server_search(c, query, tags, limit, offset)


@log_errors()
def get_trending_servers(limit: int = 6, location: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        results = _run_server_search(
            c,
            query=None,
            tags=None,
            limit=limit,
            offset=0,
            order="popularity",
            location=location,
        )
    for server in results:
        _annotate_discovery_score(server)
    results.sort(key=lambda srv: (1 if srv.get("boost_status") == BOOST_STATUS_ACTIVE else 0, srv.get("discovery_score", 0.0)), reverse=True)
    return results


@log_errors()
def get_recommended_servers(username: Optional[str], limit: int = 6, location: Optional[str] = None) -> List[Dict[str, Any]]:
    if not username:
        return get_trending_servers(limit, location=location)

    profile = get_profile(username)
    interests = profile.get("search_interests") if profile else []
    if not interests:
        return get_trending_servers(limit, location=location)

    interest_slugs: List[str] = []
    for item in interests:
        if isinstance(item, dict):
            label = item.get("label")
        else:
            label = str(item)
        if not label:
            continue
        interest_slugs.append(_slugify(label, fallback="tag"))
        if len(interest_slugs) >= SERVER_TOPIC_TAG_LIMIT:
            break

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        recommendations = _run_server_search(
            c,
            query=None,
            tags=interest_slugs,
            limit=limit,
            offset=0,
            order="popularity",
            location=location,
        )

    if recommendations:
        for server in recommendations:
            _annotate_discovery_score(server)
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            _enrich_servers_for_viewer(
                c,
                username,
                recommendations,
                interest_slugs=_extract_interest_slugs_from_profile(profile),
            )
        recommendations.sort(
            key=lambda srv: (
                1 if srv.get("boost_status") == BOOST_STATUS_ACTIVE else 0,
                srv.get("personalized_score", srv.get("discovery_score", 0.0)),
            ),
            reverse=True,
        )
        return recommendations
    fallback = get_trending_servers(limit, location=location)
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        _enrich_servers_for_viewer(
            c,
            username,
            fallback,
            interest_slugs=_extract_interest_slugs_from_profile(profile),
        )
    fallback.sort(
        key=lambda srv: (
            1 if srv.get("boost_status") == BOOST_STATUS_ACTIVE else 0,
            srv.get("personalized_score", srv.get("discovery_score", 0.0)),
        ),
        reverse=True,
    )
    return fallback


@log_errors()
def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    if not username:
        return None

    query = """
        SELECT id,
               username,
               email,
               password,
               role,
               verified,
               active,
               created_at,
               last_login,
               login_count,
               phone_number,
               email_notifications,
               sms_notifications,
               tos_agreed,
               tos_agreed_at
        FROM users
        WHERE username = ?
    """

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql(query), (username,))
        row = c.fetchone()
    return _user_row_to_dict(row)


@log_errors()
def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None

    query = """
        SELECT id,
               username,
               email,
               password,
               role,
               verified,
               active,
               created_at,
               last_login,
               login_count,
               phone_number,
               email_notifications,
               sms_notifications,
               tos_agreed,
               tos_agreed_at
        FROM users
        WHERE LOWER(email) = LOWER(?)
    """

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql(query), (email,))
        row = c.fetchone()
    return _user_row_to_dict(row)


@log_errors()
def create_user_db(username: str,
                   email: str,
                   password_hash: str,
                   *,
                   role: str = "user",
                   verified: bool = False,
                   active: bool = True,
                   phone_number: Optional[str] = None,
                   email_notifications: bool = True,
                   sms_notifications: bool = False,
                   tos_agreed: bool = False,
                   tos_agreed_at: Optional[datetime] = None) -> Dict[str, Any]:
    if not username or not email or not password_hash:
        raise ValueError("username, email, and password_hash are required")

    normalized_role = (role or "user").strip() or "user"
    now = datetime.now()
    tos_at = tos_agreed_at or (now if tos_agreed else None)

    existing = get_user_by_username(username)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if existing:
            c.execute(_prepare_sql("""
                UPDATE users
                SET email = ?,
                    password = ?,
                    role = ?,
                    verified = ?,
                    active = ?,
                    phone_number = ?,
                    email_notifications = ?,
                    sms_notifications = ?,
                    tos_agreed = ?,
                    tos_agreed_at = ?
                WHERE username = ?
            """), (
                email,
                password_hash,
                normalized_role,
                bool(verified),
                bool(active),
                phone_number,
                bool(email_notifications),
                bool(sms_notifications),
                bool(tos_agreed),
                tos_at,
                username,
            ))
        else:
            c.execute(_prepare_sql("""
                INSERT INTO users (
                    username,
                    email,
                    password,
                    role,
                    verified,
                    active,
                    created_at,
                    last_login,
                    login_count,
                    phone_number,
                    email_notifications,
                    sms_notifications,
                    tos_agreed,
                    tos_agreed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """), (
                username,
                email,
                password_hash,
                normalized_role,
                bool(verified),
                bool(active),
                now,
                None,
                0,
                phone_number,
                bool(email_notifications),
                bool(sms_notifications),
                bool(tos_agreed),
                tos_at,
            ))
        conn.commit()

    created = get_user_by_username(username)
    return created or {}


@log_errors()
def get_all_servers(limit: int = 500, offset: int = 0) -> List[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        results = _run_server_search(
            c,
            query=None,
            tags=None,
            limit=limit,
            offset=offset,
            include_non_public=True,
            order="name",
        )
    for server in results:
        _annotate_discovery_score(server)
    return results


@log_errors()
def update_user_login(username):
    """Update user login timestamp and count"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE users 
            SET last_login = ?, login_count = login_count + 1 
            WHERE username = ?
        """, (datetime.now(), username))
        conn.commit()


@log_errors()
def _update_user_login_and_log_activity_sync(username, ip_address=None, user_agent=None):
    """Synchronous version - used by background worker only"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        try:
            # Update login tracking
            c.execute("""
                UPDATE users 
                SET last_login = ?, login_count = login_count + 1 
                WHERE username = ?
            """, (datetime.now(), username))
            
            # Log activity
            c.execute("""
                INSERT INTO user_activity (username, action, details, ip_address, user_agent, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (username, 'login', 'User logged in', ip_address, user_agent, datetime.now()))
            
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e

@log_errors()
def update_user_login_and_log_activity(username, ip_address=None, user_agent=None):
    """Async version - queues the operation for background processing"""
    try:
        event_data = {
            'type': 'login',
            'username': username,
            'ip_address': ip_address,
            'user_agent': user_agent
        }
        
        # Try to add to queue without blocking
        try:
            _activity_log_queue.put_nowait(event_data)
        except Exception:
            # Queue is full, log to file instead
            logger.warning(f"Activity log queue full. Login: {username}")
    except Exception as e:
        # Don't let logging errors block the login
        logger.error(f"Error queuing login activity: {e}")


@log_errors()
def record_tos_agreement(username):
    """Record that a user has agreed to the Terms of Service"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE users 
                SET tos_agreed = ?, tos_agreed_at = ? 
                WHERE username = ?
            """, (True, datetime.now(), username))
            conn.commit()
            logger.info(f"ToS agreement recorded for user: {username}")
            return True
    except Exception as e:
        logger.error(f"Failed to record ToS agreement for {username}: {e}")
        return False


@log_errors()
def get_tos_agreement(username):
    """Check if a user has agreed to the Terms of Service"""
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT tos_agreed, tos_agreed_at 
                FROM users 
                WHERE username = ?
            """, (username,))
            result = c.fetchone()
            if result:
                return {
                    'agreed': bool(result[0]),
                    'agreed_at': result[1]
                }
            return None
    except Exception as e:
        logger.error(f"Failed to get ToS agreement for {username}: {e}")
        return None


@log_errors()
def get_all_users():
    """Get all users from database"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, email, password, verified, role, active, created_at, last_login, login_count 
            FROM users ORDER BY created_at DESC
        """)
        users = c.fetchall()
        return users


@log_errors()
def get_all_user_emails():
    """Get summary email info for all users (admin directory)"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, email, verified, email_notifications, active, created_at
            FROM users
            ORDER BY created_at DESC
        """)
        return c.fetchall()


@log_errors()
def get_user_count():
    """Get total number of users"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        count = c.fetchone()[0]
        return count


@log_errors()
def update_user_role(username, role):
    """Update user role"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET role = ? WHERE username = ?", (role, username))
        conn.commit()
        logger.info(f"Updated role for user {username} to {role}")


@log_errors()
def deactivate_user(username):
    """Deactivate a user account"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET active = 0 WHERE username = ?", (username,))
        conn.commit()
        logger.info(f"Deactivated user: {username}")


# ======================
# NOTIFICATION PREFERENCES
# ======================

@log_errors()
def get_notification_preferences(username):
    """
    Get notification preferences for a user
    
    Returns:
        dict: {
            'email': email_address,
            'phone_number': phone_number,
            'email_notifications': bool,
            'sms_notifications': bool
        }
    """
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT email, phone_number, email_notifications, sms_notifications 
            FROM users 
            WHERE username = ?
        """, (username,))
        row = c.fetchone()
        if row:
            return {
                'email': row[0],
                'phone_number': row[1],
                'email_notifications': bool(row[2]),
                'sms_notifications': bool(row[3])
            }
        return None


@log_errors()
def update_notification_preferences(username, email_notifications=None, sms_notifications=None, phone_number=None):
    """
    Update notification preferences for a user
    
    Args:
        username: Username
        email_notifications: Enable/disable email notifications (bool, optional)
        sms_notifications: Enable/disable SMS notifications (bool, optional)
        phone_number: Phone number for SMS (str, optional)
    """
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        updates = []
        params = []
        
        if email_notifications is not None:
            updates.append("email_notifications = ?")
            params.append(1 if email_notifications else 0)
        
        if sms_notifications is not None:
            updates.append("sms_notifications = ?")
            params.append(1 if sms_notifications else 0)
        
        if phone_number is not None:
            updates.append("phone_number = ?")
            params.append(phone_number)
        
        if updates:
            params.append(username)
            query = f"UPDATE users SET {', '.join(updates)} WHERE username = ?"
            c.execute(query, params)
            conn.commit()
            logger.info(f"Updated notification preferences for user {username}")
        else:
            logger.warning(f"No notification preferences to update for user {username}")


@log_errors()
def get_users_with_notifications_enabled():
    """
    Get all active users who have at least one notification type enabled
    
    Returns:
        list: List of dicts containing user info and notification preferences
    """
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, email, phone_number, email_notifications, sms_notifications
            FROM users
            WHERE active = 1 AND (email_notifications = 1 OR sms_notifications = 1)
        """)
        rows = c.fetchall()
        return [
            {
                'username': row[0],
                'email': row[1],
                'phone_number': row[2],
                'email_notifications': bool(row[3]),
                'sms_notifications': bool(row[4])
            }
            for row in rows
        ]
# ======================
# SETTINGS MANAGEMENT
# ======================

@log_errors()
def get_settings(username=None):
    """Get settings for a specific user, or global settings if username is None"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if username:
            c.execute("SELECT key, value FROM settings WHERE username = ?", (username,))
        else:
            c.execute("SELECT key, value FROM settings WHERE username IS NULL")
        settings = dict(c.fetchall())

        # Automatically align refresh interval with subscription tier
        try:
            from subscriptions import SubscriptionManager  # Imported lazily to avoid circular deps

            tier = 'free'
            if username:
                subscription = get_user_subscription(username)
                tier = subscription.get('tier', 'free')

            interval_seconds = max(1, SubscriptionManager.get_refresh_interval(tier))
            settings['interval'] = str(interval_seconds)
        except Exception as e:
            logger.warning(f"Failed to apply subscription interval for {username or 'global'} settings: {e}")
            settings.setdefault('interval', '60')

        return settings
@log_errors()
def update_setting(key, value, username=None):
    """Update setting for a specific user, or global setting if username is None"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()

        # Force refresh interval to align with subscription tier
        if key == 'interval':
            try:
                from subscriptions import SubscriptionManager  # Lazy import to avoid circular deps

                tier = 'free'
                if username:
                    subscription = get_user_subscription(username)
                    tier = subscription.get('tier', 'free')

                interval_seconds = max(1, SubscriptionManager.get_refresh_interval(tier))
                value = str(interval_seconds)
            except Exception as e:
                logger.warning(f"Failed to enforce subscription interval for {username or 'global'}: {e}")
                value = str(value)
        else:
            value = str(value)

        c.execute("""
            INSERT OR REPLACE INTO settings (username, key, value, updated_at) 
            VALUES (?, ?, ?, ?)
        """, (username, key, value, datetime.now()))
        conn.commit()
# ======================
# USER ACTIVITY LOGGING
# ======================

@log_errors()
def get_recent_failed_logins(username, ip_address, hours=1):
    """Get recent failed login attempts for security monitoring"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        cutoff_time = datetime.now() - timedelta(hours=hours)
        c.execute("""
            SELECT username, action, ip_address, timestamp
            FROM user_activity 
            WHERE (username = ? OR ip_address = ?) 
            AND action = 'login_failed' 
            AND timestamp > ?
            ORDER BY timestamp DESC
        """, (username, ip_address, cutoff_time))
        return c.fetchall()

@log_errors()
def _log_user_activity_sync(username, action, details=None, ip_address=None, user_agent=None):
    """Synchronous version - used by background worker only"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        timestamp = datetime.now()
        # Check if user exists before logging activity
        c.execute("SELECT username FROM users WHERE username = ?", (username,))
        user_exists = c.fetchone()
        
        if not user_exists and action in ['login_failed', 'login_attempt']:
            reason = f"{action}:nonexistent_user:{username}"
            try:
                log_security_event(
                    ip_address or "unknown",
                    "/login",
                    user_agent or "unknown",
                    reason,
                    timestamp=timestamp
                )
            except Exception as security_error:
                logger.warning(f"Failed to log security event for {username}: {security_error}")
            return
        elif user_exists:
            # Normal logging for existing users
            c.execute("""
                INSERT INTO user_activity (username, action, details, ip_address, user_agent, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (username, action, details, ip_address, user_agent, timestamp))
        else:
            # Skip logging for non-existent users on other actions
            logger.warning(f"Skipping activity log for non-existent user: {username}")
            return
        
        conn.commit()

def log_user_activity(username, action, details=None, ip_address=None, user_agent=None):
    """Async version - queues the operation for background processing"""
    try:
        event_data = {
            'type': 'activity',
            'username': username,
            'action': action,
            'details': details,
            'ip_address': ip_address,
            'user_agent': user_agent
        }
        
        # Try to add to queue without blocking
        try:
            _activity_log_queue.put_nowait(event_data)
        except Exception:
            # Queue is full, log to file instead
            logger.warning(f"Activity log queue full. Activity: {username} - {action}")
    except Exception as e:
        # Don't let logging errors block the request
        logger.error(f"Error queuing user activity: {e}")


@log_errors()
def get_user_activity(username, limit=100):
    """Get recent activity for a user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT action, details, ip_address, timestamp 
            FROM user_activity 
            WHERE username = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (username, limit))
        activity = c.fetchall()
        return activity


@log_errors()
def get_recent_activity(limit=100):
    """Get recent activity across all users (admin function)"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, action, details, ip_address, timestamp 
            FROM user_activity 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (limit,))
        activity = c.fetchall()
        return activity


# ======================
# SUPPORT TICKETS
# ======================


@log_errors()
def create_support_ticket(reporter_username: str,
                          subject: str,
                          body: str,
                          *,
                          server_id: Optional[int] = None,
                          severity: str = "medium",
                          assigned_to: Optional[str] = None,
                          metadata: Optional[Dict[str, Any]] = None,
                          related_report_id: Optional[int] = None,
                          related_digest_id: Optional[int] = None) -> Dict[str, Any]:
    subject_normalized = (subject or "").strip()
    body_normalized = (body or "").strip()
    if not reporter_username:
        raise ValueError("reporter_username is required")
    if not subject_normalized:
        raise ValueError("subject is required")
    if not body_normalized:
        raise ValueError("body is required")

    severity_normalized = _normalize_ticket_severity(severity)
    metadata_payload = metadata if isinstance(metadata, dict) else {}

    if assigned_to:
        assignee = get_user_by_username(assigned_to)
        if not assignee:
            raise ValueError("Assigned user not found")

    if server_id:
        server_row = get_server_by_id(server_id, viewer_username=reporter_username, include_channels=False, include_roles=False)
        if not server_row:
            raise ValueError("Server not found")

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        now = datetime.now()
        c.execute(_prepare_sql("""
            INSERT INTO support_tickets (
                server_id,
                reporter_username,
                subject,
                body,
                status,
                severity,
                assigned_to,
                related_report_id,
                related_digest_id,
                metadata,
                created_at,
                updated_at,
                last_activity_at
            ) VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            server_id,
            reporter_username,
            subject_normalized,
            body_normalized,
            severity_normalized,
            assigned_to,
            related_report_id,
            related_digest_id,
            _dump_json(metadata_payload),
            now,
            now,
            now,
        ))
        ticket_id = c.lastrowid

        cursor_row = _select_support_ticket_row(c, ticket_id)
        ticket = _support_ticket_row_to_dict(cursor_row)

        _record_ticket_event(
            c,
            ticket,
            reporter_username,
            "created",
            comment=body_normalized,
            metadata={"severity": severity_normalized},
        )
        conn.commit()

    return get_support_ticket(ticket_id, reporter_username)


@log_errors()
def add_support_ticket_event(ticket_id: int,
                             actor_username: str,
                             event_type: str,
                             comment: Optional[str] = None,
                             metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not event_type:
        raise ValueError("event_type is required")

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        row = _select_support_ticket_row(c, ticket_id)
        if not row:
            raise ValueError("Support ticket not found")
        ticket = _support_ticket_row_to_dict(row)
        if event_type in {"status_change", "assignment", "severity_change"}:
            if not _user_can_update_ticket(ticket, actor_username):
                raise PermissionError("Forbidden")
        else:
            if not _user_can_comment_ticket(ticket, actor_username):
                raise PermissionError("Forbidden")

        event = _record_ticket_event(c, ticket, actor_username, event_type, comment=comment, metadata=metadata)
        conn.commit()
    return event


@log_errors()
def list_support_ticket_events(ticket_id: int,
                               viewer_username: str,
                               limit: int = 50) -> List[Dict[str, Any]]:
    bounded_limit = max(1, min(int(limit), 200))
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        row = _select_support_ticket_row(c, ticket_id)
        if not row:
            raise ValueError("Support ticket not found")
        ticket = _support_ticket_row_to_dict(row)
        if not _user_can_view_ticket(ticket, viewer_username):
            raise PermissionError("Forbidden")

        rows = _select_support_ticket_events(c, ticket_id, bounded_limit)
    return [_support_ticket_event_row_to_dict(event_row) for event_row in rows]


@log_errors()
def get_support_ticket(ticket_id: int,
                       viewer_username: str,
                       *,
                       include_events: bool = True,
                       event_limit: int = 50) -> Optional[Dict[str, Any]]:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        row = _select_support_ticket_row(c, ticket_id)
        if not row:
            return None
        ticket = _support_ticket_row_to_dict(row)
        if not _user_can_view_ticket(ticket, viewer_username):
            raise PermissionError("Forbidden")

        if include_events:
            rows = _select_support_ticket_events(c, ticket_id, max(1, min(int(event_limit), 200)))
            ticket["events"] = [_support_ticket_event_row_to_dict(event_row) for event_row in rows]
        else:
            ticket["events"] = []
    return ticket


@log_errors()
def list_support_tickets(viewer_username: str,
                         *,
                         status: Optional[str] = None,
                         severity: Optional[str] = None,
                         assigned_to: Optional[str] = None,
                         server_id: Optional[int] = None,
                         reporter_username: Optional[str] = None,
                         limit: int = 50,
                         offset: int = 0) -> Dict[str, Any]:
    bounded_limit = max(1, min(int(limit), 200))
    bounded_offset = max(0, int(offset))

    where_clauses: List[str] = []
    params: List[Any] = []

    if status:
        where_clauses.append("t.status = ?")
        params.append(_normalize_ticket_status(status))
    if severity:
        where_clauses.append("t.severity = ?")
        params.append(_normalize_ticket_severity(severity))
    if assigned_to:
        where_clauses.append("t.assigned_to = ?")
        params.append(assigned_to)
    if server_id:
        where_clauses.append("t.server_id = ?")
        params.append(int(server_id))
    if reporter_username:
        where_clauses.append("t.reporter_username = ?")
        params.append(reporter_username)

    is_admin = _is_admin_user(viewer_username)
    access_params: List[Any] = []
    access_clause = ""
    if not is_admin:
        owned_server_ids = {
            server["id"]
            for server in list_user_servers(viewer_username, status_filter=None, limit=200)
            if server.get("owner_username") == viewer_username
        }
        clause_parts = ["t.reporter_username = ?", "t.assigned_to = ?"]
        access_params.extend([viewer_username, viewer_username])
        if owned_server_ids:
            placeholders = ", ".join("?" for _ in owned_server_ids)
            clause_parts.append(f"t.server_id IN ({placeholders})")
            access_params.extend(list(owned_server_ids))
        access_clause = "(" + " OR ".join(clause_parts) + ")"
        where_clauses.append(access_clause)

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    query_params = tuple(params + access_params + [bounded_limit, bounded_offset])

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql(_SUPPORT_TICKET_SELECT_BASE + f"""
            {where_sql}
            ORDER BY t.created_at DESC, t.id DESC
            LIMIT ?
            OFFSET ?
        """), query_params)
        rows = c.fetchall()

        count_params = tuple(params + access_params)
        c.execute(_prepare_sql(f"""
            SELECT COUNT(*)
            FROM support_tickets t
            LEFT JOIN servers s ON s.id = t.server_id
            {where_sql}
        """), count_params)
        total = int(c.fetchone()[0] or 0)

    tickets = [_support_ticket_row_to_dict(row) for row in rows]
    for ticket in tickets:
        ticket["events"] = []

    return {
        "tickets": tickets,
        "total": total,
        "limit": bounded_limit,
        "offset": bounded_offset,
    }


@log_errors()
def update_support_ticket(ticket_id: int,
                          actor_username: str,
                          *,
                          status: Optional[str] = None,
                          severity: Optional[str] = None,
                          assigned_to: Optional[str] = None,
                          metadata_updates: Optional[Dict[str, Any]] = None,
                          comment: Optional[str] = None,
                          comment_type: str = "comment") -> Dict[str, Any]:
    normalized_status = None
    if status is not None:
        normalized_status = _normalize_ticket_status(status)
    normalized_severity = None
    if severity is not None:
        normalized_severity = _normalize_ticket_severity(severity)

    if assigned_to:
        assignee = get_user_by_username(assigned_to)
        if not assignee:
            raise ValueError("Assigned user not found")

    metadata_updates = metadata_updates if isinstance(metadata_updates, dict) else None

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        row = _select_support_ticket_row(c, ticket_id)
        if not row:
            raise ValueError("Support ticket not found")
        ticket = _support_ticket_row_to_dict(row)
        if not _user_can_view_ticket(ticket, actor_username):
            raise PermissionError("Forbidden")

        now = datetime.now()
        status_changed = False
        severity_changed = False
        assignment_changed = False
        metadata_changed = False

        update_fields: List[str] = []
        update_params: List[Any] = []

        if normalized_status and normalized_status != ticket["status"]:
            if not _user_can_update_ticket(ticket, actor_username):
                raise PermissionError("Forbidden")
            update_fields.append("status = ?")
            update_params.append(normalized_status)
            status_changed = True
            if normalized_status == "resolved":
                update_fields.append("resolved_at = ?")
                update_params.append(now)
                ticket["resolved_at"] = _to_datetime_string(now)
            elif ticket.get("resolved_at"):
                update_fields.append("resolved_at = NULL")
                ticket["resolved_at"] = None
            ticket["status"] = normalized_status

        if normalized_severity and normalized_severity != ticket["severity"]:
            if not _user_can_update_ticket(ticket, actor_username):
                raise PermissionError("Forbidden")
            update_fields.append("severity = ?")
            update_params.append(normalized_severity)
            severity_changed = True
            ticket["severity"] = normalized_severity

        assigned_target = assigned_to
        if assigned_target is not None:
            assigned_target = assigned_target.strip() or None
            if assigned_target != ticket.get("assigned_to"):
                if assigned_target:
                    assignee = get_user_by_username(assigned_target)
                    if not assignee:
                        raise ValueError("Assigned user not found")
                if not _user_can_update_ticket(ticket, actor_username):
                    raise PermissionError("Forbidden")
                if assigned_target:
                    update_fields.append("assigned_to = ?")
                    update_params.append(assigned_target)
                else:
                    update_fields.append("assigned_to = NULL")
                assignment_changed = True
                ticket["assigned_to"] = assigned_target

        if metadata_updates:
            merged_metadata = _merge_ticket_metadata(ticket.get("metadata"), metadata_updates)
            update_fields.append("metadata = ?")
            update_params.append(_dump_json(merged_metadata))
            metadata_changed = True
            ticket["metadata"] = merged_metadata

        if update_fields:
            c.execute(_prepare_sql(f"""
                UPDATE support_tickets
                SET {', '.join(update_fields)}
                WHERE id = ?
            """), (*update_params, ticket_id))

        if status_changed:
            _record_ticket_event(
                c,
                ticket,
                actor_username,
                "status_change",
                comment=f"Status changed to {ticket['status']}",
                metadata={"status": ticket["status"]},
            )

        if severity_changed:
            _record_ticket_event(
                c,
                ticket,
                actor_username,
                "severity_change",
                comment=f"Severity changed to {ticket['severity']}",
                metadata={"severity": ticket["severity"]},
            )

        if assignment_changed:
            assigned_comment = f"Ticket assigned to {ticket['assigned_to']}" if ticket["assigned_to"] else "Ticket unassigned"
            _record_ticket_event(
                c,
                ticket,
                actor_username,
                "assignment",
                comment=assigned_comment,
                metadata={"assigned_to": ticket["assigned_to"]},
            )

        if metadata_changed:
            _record_ticket_event(
                c,
                ticket,
                actor_username,
                "metadata_update",
                comment="Ticket metadata updated",
                metadata=metadata_updates,
            )

        if comment:
            if not _user_can_comment_ticket(ticket, actor_username):
                raise PermissionError("Forbidden")
            event_type = comment_type or "comment"
            _record_ticket_event(
                c,
                ticket,
                actor_username,
                event_type,
                comment=comment,
            )

        conn.commit()

    return get_support_ticket(ticket_id, actor_username)


@log_errors()
def get_support_metrics(window_hours: int = 720,
                         *,
                         server_id: Optional[int] = None,
                         assigned_to: Optional[str] = None) -> Dict[str, Any]:
    bounded_window = max(1, min(int(window_hours), 24 * 90))
    cutoff = datetime.now() - timedelta(hours=bounded_window)

    where_clauses = ["created_at >= ?"]
    params: List[Any] = [cutoff]

    if server_id:
        where_clauses.append("server_id = ?")
        params.append(server_id)
    if assigned_to:
        where_clauses.append("assigned_to = ?")
        params.append(assigned_to)

    where_sql = " AND ".join(where_clauses)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(_prepare_sql(f"""
            SELECT id,
                   status,
                   severity,
                   created_at,
                   first_response_at,
                   resolved_at,
                   last_activity_at
            FROM support_tickets
            WHERE {where_sql}
        """), tuple(params))
        rows = c.fetchall()

    open_count = 0
    status_counts: Dict[str, int] = defaultdict(int)
    severity_counts: Dict[str, int] = defaultdict(int)
    response_durations: List[float] = []
    resolution_durations: List[float] = []
    response_breaches = 0
    resolution_breaches = 0

    for row in rows:
        _, status, severity, created_at, first_response_at, resolved_at, _ = row
        status = (status or "").lower()
        severity = (severity or "medium").lower()
        status_counts[status] += 1
        severity_counts[severity] += 1

        created_dt = _parse_db_datetime(created_at) or cutoff
        first_response_dt = _parse_db_datetime(first_response_at)
        resolved_dt = _parse_db_datetime(resolved_at)

        if status in {"open", "in_progress", "waiting"}:
            open_count += 1

        if first_response_dt:
            hours_to_response = (first_response_dt - created_dt).total_seconds() / 3600.0
            if hours_to_response >= 0:
                response_durations.append(hours_to_response)
                sla_hours = SUPPORT_SLA_RESPONSE_HOURS.get(severity, SUPPORT_SLA_RESPONSE_HOURS["medium"])
                if hours_to_response > sla_hours:
                    response_breaches += 1
        else:
            # still awaiting response
            sla_hours = SUPPORT_SLA_RESPONSE_HOURS.get(severity, SUPPORT_SLA_RESPONSE_HOURS["medium"])
            hours_since_creation = (datetime.now() - created_dt).total_seconds() / 3600.0
            if hours_since_creation > sla_hours:
                response_breaches += 1

        if resolved_dt:
            hours_to_resolution = (resolved_dt - created_dt).total_seconds() / 3600.0
            if hours_to_resolution >= 0:
                resolution_durations.append(hours_to_resolution)
                sla_hours = SUPPORT_SLA_RESOLUTION_HOURS.get(severity, SUPPORT_SLA_RESOLUTION_HOURS["medium"])
                if hours_to_resolution > sla_hours:
                    resolution_breaches += 1
        elif status in {"resolved", "closed"}:
            # resolved timestamp missing but status indicates closure
            resolution_breaches += 1

    def _avg(values: List[float]) -> Optional[float]:
        return round(sum(values) / len(values), 2) if values else None

    def _median(values: List[float]) -> Optional[float]:
        return round(statistics.median(values), 2) if values else None

    metrics = {
        "window_hours": bounded_window,
        "tickets_considered": len(rows),
        "open_count": open_count,
        "open_by_status": {status: count for status, count in status_counts.items() if count},
        "open_by_severity": {
            severity: count
            for severity, count in severity_counts.items()
            if severity in SUPPORT_TICKET_SEVERITIES and count
        },
        "avg_first_response_hours": _avg(response_durations),
        "median_first_response_hours": _median(response_durations),
        "avg_resolution_hours": _avg(resolution_durations),
        "median_resolution_hours": _median(resolution_durations),
        "response_sla_breach_count": response_breaches,
        "resolution_sla_breach_count": resolution_breaches,
    }
    return metrics


# ======================
# DATA EXPORT / SCRUB
# ======================


def _collect_server_ids_for_user(username: str, cursor: sqlite3.Cursor) -> Set[int]:
    cursor.execute("""
        SELECT DISTINCT server_id
        FROM server_memberships
        WHERE username = ?
    """, (username,))
    membership_ids = {row[0] for row in cursor.fetchall() if row[0]}

    cursor.execute("""
        SELECT id
        FROM servers
        WHERE owner_username = ?
    """, (username,))
    owned_ids = {row[0] for row in cursor.fetchall() if row[0]}
    return membership_ids.union(owned_ids)


@log_errors()
def purge_user_data(username: str) -> None:
    if not username:
        return

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        server_ids = _collect_server_ids_for_user(username, c)

        # Support ticket visibility
        c.execute("""
            UPDATE support_ticket_events
            SET actor_username = NULL
            WHERE actor_username = ?
        """, (username,))

        c.execute("""
            UPDATE support_tickets
            SET assigned_to = NULL
            WHERE assigned_to = ?
        """, (username,))

        c.execute("""
            DELETE FROM support_tickets
            WHERE reporter_username = ?
        """, (username,))

        # Direct messaging
        c.execute("""
            DELETE FROM dm_message_reactions
            WHERE username = ?
        """, (username,))
        c.execute("""
            DELETE FROM dm_messages
            WHERE sender_id = ?
        """, (username,))
        c.execute("""
            DELETE FROM dm_participants
            WHERE username = ?
        """, (username,))
        c.execute("""
            UPDATE dm_conversations
            SET created_by = NULL,
                metadata = json_set(COALESCE(metadata, '{}'), '$.__anonymized', 1)
            WHERE created_by = ?
        """, (username,))

        # Channel messages
        c.execute("""
            DELETE FROM message_reactions
            WHERE username = ?
        """, (username,))
        c.execute("""
            DELETE FROM messages
            WHERE sender_id = ?
        """, (username,))

        # Tickets, reports, moderation
        c.execute("""
            UPDATE reports
            SET reporter_username = NULL
            WHERE reporter_username = ?
        """, (username,))

        c.execute("""
            UPDATE moderation_actions
            SET actor_username = NULL
            WHERE actor_username = ?
        """, (username,))

        c.execute("""
            DELETE FROM moderation_actions
            WHERE target_type = 'user' AND target_id = ?
        """, (username,))

        # Servers owned by user: transfer or delete
        for server_id in server_ids:
            c.execute("""
                SELECT owner_username
                FROM servers
                WHERE id = ?
            """, (server_id,))
            row = c.fetchone()
            if row and row[0] == username:
                c.execute("DELETE FROM servers WHERE id = ?", (server_id,))

        # Remove memberships and roles
        c.execute("""
            DELETE FROM server_memberships
            WHERE username = ?
        """, (username,))

        c.execute("""
            UPDATE server_invites
            SET created_by = NULL,
                metadata = json_set(COALESCE(metadata, '{}'), '$.__anonymized', 1)
            WHERE created_by = ?
        """, (username,))

        # Favorites, tips, referrals, engagements
        c.execute("DELETE FROM server_tip_dismissals WHERE username = ?", (username,))
        c.execute("DELETE FROM favorites WHERE username = ?", (username,))
        c.execute("DELETE FROM referral_conversions WHERE referrer_username = ? OR referred_username = ?", (username, username))
        c.execute("DELETE FROM referral_hits WHERE referral_code_id IN (SELECT id FROM referral_codes WHERE owner_username = ?)", (username,))
        c.execute("DELETE FROM referral_hits WHERE code IN (SELECT code FROM referral_codes WHERE owner_username = ?)", (username,))
        c.execute("DELETE FROM referral_codes WHERE owner_username = ?", (username,))
        c.execute("DELETE FROM user_streaks WHERE username = ?", (username,))

        # Social graph
        c.execute("""
            DELETE FROM friend_requests
            WHERE requester_username = ? OR recipient_username = ?
        """, (username, username))
        c.execute("""
            DELETE FROM friendships
            WHERE owner_username = ? OR friend_username = ?
        """, (username, username))
        c.execute("""
            DELETE FROM user_blocks
            WHERE owner_username = ? OR blocked_username = ?
        """, (username, username))
        c.execute("DELETE FROM friend_request_throttle WHERE username = ?", (username,))

        # Profile and user record
        c.execute("DELETE FROM profile_activity WHERE username = ?", (username,))
        c.execute("DELETE FROM profile_showcase_items WHERE username = ?", (username,))
        c.execute("DELETE FROM profiles WHERE username = ?", (username,))
        c.execute("DELETE FROM saved_searches WHERE username = ?", (username,))
        c.execute("DELETE FROM settings WHERE username = ?", (username,))
        c.execute("DELETE FROM user_activity WHERE username = ?", (username,))
        c.execute("DELETE FROM rate_limits WHERE username = ?", (username,))
        c.execute("DELETE FROM users WHERE username = ?", (username,))

        conn.commit()


@log_errors()
def export_user_data(username: str) -> Dict[str, Any]:
    if not username:
        raise ValueError("username is required")

    export: Dict[str, Any] = {"username": username}

    with get_pool().get_connection() as conn:
        c = conn.cursor()

        c.execute("""
            SELECT username,
                   email,
                   role,
                   verified,
                   active,
                   created_at,
                   last_login,
                   login_count
            FROM users
            WHERE username = ?
        """, (username,))
        user_row = c.fetchone()
        if not user_row:
            raise ValueError("User not found")
        export["user"] = _user_row_to_dict(user_row)

        c.execute("""
            SELECT key, value
            FROM settings
            WHERE username = ?
        """, (username,))
        export["settings"] = {row[0]: row[1] for row in c.fetchall()}

        c.execute("""
            SELECT id,
                   display_name,
                   bio,
                   avatar_url,
                   banner_url,
                   showcase_config,
                   visibility_settings,
                   created_at,
                   updated_at
            FROM profiles
            WHERE username = ?
        """, (username,))
        profile_row = c.fetchone()
        export["profile"] = _profile_row_to_dict(profile_row) if profile_row else {}

        c.execute("""
            SELECT server_id, status, joined_at, role_id
            FROM server_memberships
            WHERE username = ?
        """, (username,))
        export["server_memberships"] = [
            {
                "server_id": row[0],
                "status": row[1],
                "joined_at": _to_datetime_string(row[2]),
                "role_id": row[3],
            }
            for row in c.fetchall()
        ]

        c.execute("""
            SELECT tip_id, dismissed_at
            FROM server_tip_dismissals
            WHERE username = ?
        """, (username,))
        export["tip_dismissals"] = [
            {
                "tip_id": row[0],
                "dismissed_at": _to_datetime_string(row[1]),
            }
            for row in c.fetchall()
        ]

        c.execute("""
            SELECT id, title, price, link, source, created_at
            FROM listings
            WHERE user_id = ?
        """, (username,))
        export["listings"] = []
        for row in c.fetchall():
            listing_id = row[0]
            listing = get_listing_by_id(listing_id)
            if not listing:
                listing = {
                    "id": listing_id,
                    "title": row[1],
                    "price": row[2],
                    "link": row[3],
                    "source": row[4],
                    "created_at": _to_datetime_string(row[5]),
                }
            export["listings"].append(listing)

        c.execute("""
            SELECT id, keyword, count, avg_price, date, source
            FROM keyword_trends
            WHERE user_id = ?
        """, (username,))
        export["keyword_trends"] = [
            {
                "id": row[0],
                "keyword": row[1],
                "count": row[2],
                "avg_price": row[3],
                "date": _to_datetime_string(row[4]),
                "source": row[5],
            }
            for row in c.fetchall()
        ]

        c.execute("""
            SELECT id, action, details, timestamp, ip_address, user_agent
            FROM user_activity
            WHERE username = ?
            ORDER BY timestamp DESC
            LIMIT 500
        """, (username,))
        export["activity"] = [
            {
                "id": row[0],
                "action": row[1],
                "details": row[2],
                "timestamp": _to_datetime_string(row[3]),
                "ip_address": row[4],
                "user_agent": row[5],
            }
            for row in c.fetchall()
        ]

        c.execute("""
            SELECT id
            FROM support_tickets
            WHERE reporter_username = ? OR assigned_to = ?
        """, (username, username))
        ticket_ids = [row[0] for row in c.fetchall()]
        export["support_tickets"] = []
        for t_id in ticket_ids[:200]:
            ticket = get_support_ticket(t_id, username)
            if ticket:
                export["support_tickets"].append(ticket)

    return export
# ======================
# RATE LIMITING
# ======================
@log_errors()
def check_rate_limit(username, endpoint, max_requests=60, window_minutes=1):
    """
    Check if user has exceeded rate limit for an endpoint
    Returns: (is_allowed, remaining_requests)
    """
    import time
    import random
    max_retries = 5
    base_delay = 0.1  # Base delay in seconds

    def _normalize_timestamp(value):
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(value, fmt)
                except ValueError:
                    continue
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                logger.warning(f"Unable to parse timestamp '{value}' for rate limiting")
        return datetime.now()
    
    for attempt in range(max_retries):
        try:
            with get_pool().get_connection() as conn:
                now = datetime.now()
                if USE_POSTGRES:
                    c = conn.cursor()
                    c.execute("""
                        SELECT request_count, window_start 
                        FROM rate_limits 
                        WHERE username = ? AND endpoint = ?
                        FOR UPDATE
                    """, (username, endpoint))
                    result = c.fetchone()

                    if result:
                        request_count, window_start = result
                        window_start = _normalize_timestamp(window_start)

                        time_diff = (now - window_start).total_seconds() / 60

                        if time_diff < window_minutes:
                            if request_count >= max_requests:
                                conn.rollback()
                                logger.warning(f"Rate limit exceeded for {username} on {endpoint}")
                                return False, 0

                            c.execute("""
                                UPDATE rate_limits 
                                SET request_count = request_count + 1 
                                WHERE username = ? AND endpoint = ?
                            """, (username, endpoint))
                            conn.commit()
                            return True, max_requests - request_count - 1
                        else:
                            c.execute("""
                                UPDATE rate_limits 
                                SET request_count = 1, window_start = ? 
                                WHERE username = ? AND endpoint = ?
                            """, (now, username, endpoint))
                            conn.commit()
                            return True, max_requests - 1
                    else:
                        try:
                            c.execute("""
                                INSERT INTO rate_limits (username, endpoint, request_count, window_start) 
                                VALUES (?, ?, 1, ?)
                            """, (username, endpoint, now))
                            conn.commit()
                            return True, max_requests - 1
                        except Exception as insert_error:
                            conn.rollback()
                            if getattr(insert_error, "pgcode", None) == "23505" and attempt < max_retries - 1:
                                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                                logger.warning(f"Rate limit insert race condition for {username} on {endpoint}, retrying in {delay:.2f}s")
                                time.sleep(delay)
                                continue
                            raise insert_error
                else:
                    # SQLite path - use immediate transaction mode to avoid locking
                    conn.execute("BEGIN IMMEDIATE")
                    c = conn.cursor()

                    c.execute("""
                        SELECT request_count, window_start 
                        FROM rate_limits 
                        WHERE username = ? AND endpoint = ?
                    """, (username, endpoint))
                    
                    result = c.fetchone()
                    
                    if result:
                        request_count, window_start = result
                        window_start = _normalize_timestamp(window_start)
                        
                        time_diff = (now - window_start).total_seconds() / 60
                        
                        if time_diff < window_minutes:
                            if request_count >= max_requests:
                                conn.rollback()
                                logger.warning(f"Rate limit exceeded for {username} on {endpoint}")
                                return False, 0
                            
                            c.execute("""
                                UPDATE rate_limits 
                                SET request_count = request_count + 1 
                                WHERE username = ? AND endpoint = ?
                            """, (username, endpoint))
                            conn.commit()
                            return True, max_requests - request_count - 1
                        else:
                            c.execute("""
                                UPDATE rate_limits 
                                SET request_count = 1, window_start = ? 
                                WHERE username = ? AND endpoint = ?
                            """, (now, username, endpoint))
                            conn.commit()
                            return True, max_requests - 1
                    else:
                        try:
                            c.execute("""
                                INSERT INTO rate_limits (username, endpoint, request_count, window_start) 
                                VALUES (?, ?, 1, ?)
                            """, (username, endpoint, now))
                            conn.commit()
                            return True, max_requests - 1
                        except sqlite3.IntegrityError:
                            conn.rollback()
                            if attempt < max_retries - 1:
                                time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.1))
                                continue
                            else:
                                logger.warning(f"Rate limit check failed after {max_retries} attempts for {username}")
                                return True, max_requests - 1

        except sqlite3.OperationalError as e:
            if "database is locked" in str(e).lower():
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.1)
                    logger.warning(f"Database locked, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Database locked after {max_retries} attempts for {username}")
                    # Return allowed to avoid blocking legitimate users
                    return True, max_requests - 1
            else:
                logger.error(f"Database error in check_rate_limit: {e}")
                return True, max_requests - 1
        except Exception as e:
            logger.error(f"Unexpected error in check_rate_limit: {e}")
            return True, max_requests - 1
    
    # Fallback - return allowed if all retries failed
    logger.warning(f"Rate limit check failed after {max_retries} attempts for {username}")
    return True, max_requests - 1


@log_errors()
def reset_rate_limit(username: str, endpoint: str) -> bool:
    """Reset rate limiting counters for a specific user/endpoint pair."""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM rate_limits
            WHERE username = ? AND endpoint = ?
        """, (username, endpoint))
        deleted = c.rowcount > 0
        conn.commit()
    return deleted


# ======================
# FEED & NOTIFICATIONS
# ======================
def _default_feed_score(event_type: str) -> float:
    normalized = (event_type or "").lower()
    if normalized in {"server_announcement", "server_highlight"}:
        return 7.0
    if normalized in {"dm_message", "mention"}:
        return 6.5
    if normalized in {"listing_alert", "marketplace_drop"}:
        return 5.5
    return 5.0


def _summarize_feed_event(event: Dict[str, Any]) -> Dict[str, Any]:
    event_type = (event.get("event_type") or "").lower()
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}

    title = payload.get("title")
    subtitle = payload.get("subtitle")
    category = event_type or "update"
    url = payload.get("url")

    if not title:
        if event_type == "dm_message":
            sender = payload.get("sender_display") or payload.get("sender") or event.get("actor_username")
            preview = payload.get("preview") or payload.get("body") or ""
            title = f"New message from {sender}" if sender else "New direct message"
            subtitle = preview[:140] if preview else subtitle
        elif event_type in {"server_announcement", "server_highlight"}:
            server = payload.get("server_name") or event.get("server_slug")
            title = f"{server} update" if server else "Server update"
        elif event_type in {"listing_alert", "marketplace_drop"}:
            listing = payload.get("listing_title") or payload.get("preview")
            title = listing or "Listing alert"
        else:
            title = payload.get("headline") or "Community update"

    if not subtitle:
        description = payload.get("description") or payload.get("preview")
        if description:
            subtitle = description[:180]

    return {
        "title": title,
        "subtitle": subtitle,
        "category": category,
        "url": url,
    }


def _compute_feed_rank(event: Dict[str, Any]) -> float:
    score = float(event.get("score") or 0.0)
    created_at = _parse_db_datetime(event.get("created_at"))
    recency_bonus = 0.0
    if created_at:
        hours_old = max((datetime.now() - created_at).total_seconds() / 3600.0, 0.0)
        if hours_old < 1:
            recency_bonus = 6.0
        elif hours_old < 24:
            recency_bonus = max(0.0, 6.0 - hours_old * 0.25)
        elif hours_old < 72:
            recency_bonus = max(0.0, 3.0 - (hours_old - 24) * 0.05)
    audience_boost = 0.0
    audience_type = (event.get("audience_type") or "").lower()
    if audience_type == "user":
        audience_boost = 3.0
    elif audience_type == "server":
        audience_boost = 1.5
    if (event.get("event_type") or "").lower() == "server_recommendation":
        audience_boost = 0.0
        recency_bonus = round(recency_bonus * 0.5, 3)
    return round(score + recency_bonus + audience_boost, 3)


def _build_server_recommendation_event(username: str, server: Dict[str, Any]) -> Dict[str, Any]:
    personalization = server.get("personalization") or {}
    raw_score = float(server.get("personalized_score") or server.get("discovery_score") or 0.0)
    score = max(min(raw_score, 5.0), 0.5)
    friend_count = int(personalization.get("friend_member_count") or 0)
    interest_overlap = int(personalization.get("interest_overlap") or 0)
    related_servers = personalization.get("related_servers") or []

    reasons = personalization.get("reasons") or []
    subtitle_parts: List[str] = []
    if friend_count:
        subtitle_parts.append(f"{friend_count} friend{'s' if friend_count != 1 else ''} already joined")
    if interest_overlap:
        subtitle_parts.append(f"Matches your interests")
    if related_servers:
        subtitle_parts.append("Similar to servers you follow")
    if not subtitle_parts and reasons:
        subtitle_parts = reasons[:2]

    description = server.get("description") or ""
    subtitle = " · ".join(subtitle_parts) if subtitle_parts else description[:160]

    event = {
        "id": None,
        "event_type": "server_recommendation",
        "actor_username": server.get("owner_username"),
        "entity_type": "server",
        "entity_id": server.get("id"),
        "server_slug": server.get("slug"),
        "target_username": username,
        "audience_type": "user",
        "audience_id": username,
        "payload": {
            "server": {
                "slug": server.get("slug"),
                "name": server.get("name"),
                "icon_url": server.get("icon_url"),
                "banner_url": server.get("banner_url"),
                "description": description,
                "personalization": personalization,
            }
        },
        "score": score,
        "created_at": _to_datetime_string(datetime.now()),
    }
    event["summary"] = {
        "title": f"Discover {server.get('name') or 'a new server'}",
        "subtitle": subtitle or "Suggested for you",
        "category": "recommended",
        "url": f"/servers/{server.get('slug')}",
    }
    event["computed_score"] = _compute_feed_rank(event)
    return event


def _serialize_feed_event_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    payload = _load_json(row[9], {})
    if not isinstance(payload, dict):
        payload = {}

    try:
        score_value = float(row[10]) if row[10] is not None else 0.0
    except (TypeError, ValueError):
        score_value = 0.0

    event = {
        "id": row[0],
        "event_type": row[1],
        "actor_username": row[2],
        "entity_type": row[3],
        "entity_id": row[4],
        "server_slug": row[5],
        "target_username": row[6],
        "audience_type": row[7],
        "audience_id": row[8],
        "payload": payload,
        "score": score_value,
        "created_at": _to_datetime_string(row[11]),
    }
    event["summary"] = _summarize_feed_event(event)
    event["computed_score"] = _compute_feed_rank(event)
    return event


def _serialize_notification_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    payload = _load_json(row[4], {})
    if not isinstance(payload, dict):
        payload = {}

    return {
        "id": row[0],
        "username": row[1],
        "event_id": row[2],
        "notification_type": row[3],
        "payload": payload,
        "delivery_status": row[5],
        "created_at": _to_datetime_string(row[6]),
        "seen_at": _to_datetime_string(row[7]) if row[7] else None,
        "read_at": _to_datetime_string(row[8]) if row[8] else None,
    }


@log_errors()
def create_notification(
    username: str,
    notification_type: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    event_id: Optional[int] = None,
    delivery_status: Optional[str] = None,
    created_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    normalized_username = (username or "").strip()
    if not normalized_username:
        raise ValueError("username is required")

    normalized_type = (notification_type or "").strip().lower()
    if not normalized_type:
        raise ValueError("notification_type is required")

    event_id_value: Optional[int] = None
    if event_id is not None:
        try:
            event_id_value = int(event_id)
        except (TypeError, ValueError):
            raise ValueError("event_id must be an integer") from None
        if event_id_value <= 0:
            event_id_value = None

    payload_dict = payload if isinstance(payload, dict) else {}
    payload_json = _dump_json(payload_dict)
    delivery_value = (delivery_status or "in_app").strip().lower() or "in_app"
    timestamp = created_at if isinstance(created_at, datetime) else datetime.now()

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO notifications (
                username,
                event_id,
                notification_type,
                payload,
                delivery_status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_username,
                event_id_value,
                normalized_type,
                payload_json,
                delivery_value,
                timestamp,
            ),
        )
        notification_id = c.lastrowid
        conn.commit()
        c.execute(
            """
            SELECT id,
                   username,
                   event_id,
                   notification_type,
                   payload,
                   delivery_status,
                   created_at,
                   seen_at,
                   read_at
            FROM notifications
            WHERE id = ?
            """,
            (notification_id,),
        )
        row = c.fetchone()

    if row:
        return _serialize_notification_row(row)

    return {
        "id": notification_id,
        "username": normalized_username,
        "event_id": event_id_value,
        "notification_type": normalized_type,
        "payload": payload_dict,
        "delivery_status": delivery_value,
        "created_at": _to_datetime_string(timestamp),
        "seen_at": None,
        "read_at": None,
    }


@log_errors()
def get_notifications(
    username: Optional[str],
    *,
    limit: int = 50,
    include_read: bool = False,
    offset: int = 0,
) -> Dict[str, Any]:
    normalized_username = (username or "").strip()
    if not normalized_username:
        return {
            "notifications": [],
            "meta": {"limit": 0, "offset": 0, "next_offset": None, "total": 0},
            "unread_count": 0,
            "include_read": include_read,
        }

    try:
        limit_value = max(1, min(int(limit), 200))
    except (TypeError, ValueError):
        limit_value = 50

    try:
        offset_value = max(0, int(offset))
    except (TypeError, ValueError):
        offset_value = 0

    filters = ["username = ?"]
    params: List[Any] = [normalized_username]

    if not include_read:
        filters.append("read_at IS NULL")

    where_clause = " AND ".join(filters)

    count_query = f"SELECT COUNT(*) FROM notifications WHERE {where_clause}"
    data_query = f"""
        SELECT
            id,
            username,
            event_id,
            notification_type,
            payload,
            delivery_status,
            created_at,
            seen_at,
            read_at
        FROM notifications
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """

    data_params = list(params) + [limit_value, offset_value]

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(count_query, tuple(params))
        total_row = c.fetchone()
        total = int(total_row[0]) if total_row else 0

        c.execute(data_query, tuple(data_params))
        rows = c.fetchall()

        c.execute(
            """
            SELECT COUNT(*)
            FROM notifications
            WHERE username = ? AND read_at IS NULL
            """,
            (normalized_username,),
        )
        unread_row = c.fetchone()
        unread_count = int(unread_row[0]) if unread_row else 0

    notifications = [_serialize_notification_row(row) for row in rows]
    next_offset = offset_value + limit_value if offset_value + limit_value < total else None

    return {
        "notifications": notifications,
        "meta": {
            "limit": limit_value,
            "offset": offset_value,
            "next_offset": next_offset,
            "total": total,
        },
        "unread_count": unread_count,
        "include_read": include_read,
    }


@log_errors()
def mark_notifications_seen(username: Optional[str], notification_ids: Iterable[Any]) -> int:
    normalized_username = (username or "").strip()
    if not normalized_username:
        return 0

    ids = _normalize_int_list(notification_ids or [])
    if not ids:
        return 0

    placeholders = ",".join("?" for _ in ids)
    query = f"""
        UPDATE notifications
        SET seen_at = COALESCE(seen_at, CURRENT_TIMESTAMP)
        WHERE username = ? AND id IN ({placeholders}) AND seen_at IS NULL
    """
    params: List[Any] = [normalized_username, *ids]

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(query, tuple(params))
        updated = c.rowcount or 0
        conn.commit()

    return updated


@log_errors()
def mark_notifications_read(username: Optional[str], notification_ids: Iterable[Any]) -> int:
    normalized_username = (username or "").strip()
    if not normalized_username:
        return 0

    ids = _normalize_int_list(notification_ids or [])
    if not ids:
        return 0

    placeholders = ",".join("?" for _ in ids)
    query = f"""
        UPDATE notifications
        SET
            read_at = COALESCE(read_at, CURRENT_TIMESTAMP),
            seen_at = COALESCE(seen_at, CURRENT_TIMESTAMP)
        WHERE username = ? AND id IN ({placeholders}) AND read_at IS NULL
    """
    params: List[Any] = [normalized_username, *ids]

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(query, tuple(params))
        updated = c.rowcount or 0
        conn.commit()

    return updated


@log_errors()
def mark_all_notifications_read(username: Optional[str]) -> int:
    normalized_username = (username or "").strip()
    if not normalized_username:
        return 0

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            UPDATE notifications
            SET
                read_at = COALESCE(read_at, CURRENT_TIMESTAMP),
                seen_at = COALESCE(seen_at, CURRENT_TIMESTAMP)
            WHERE username = ? AND read_at IS NULL
            """,
            (normalized_username,),
        )
        updated = c.rowcount or 0
        conn.commit()

    return updated


@log_errors()
def dismiss_notification(username: Optional[str], notification_id: Any) -> bool:
    normalized_username = (username or "").strip()
    if not normalized_username:
        return False

    try:
        notification_id_value = int(notification_id)
    except (TypeError, ValueError):
        return False

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM notifications WHERE id = ? AND username = ?",
            (notification_id_value, normalized_username),
        )
        deleted = c.rowcount or 0
        conn.commit()

    return deleted > 0


@log_errors()
def record_slow_mode_violation(
    server_id: Optional[int],
    channel_id: Optional[int],
    username: Optional[str],
    retry_after: Optional[float],
) -> None:
    """Record a slow-mode violation attempt for observability."""
    try:
        retry_after_value = float(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        retry_after_value = None

    log_event(
        "realtime.slow_mode_violation",
        severity="warning",
        server_id=server_id,
        channel_id=channel_id,
        username=username,
        retry_after=retry_after_value,
    )


@log_errors()
def log_feed_event(
    event_type: str,
    *,
    actor_username: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    server_slug: Optional[str] = None,
    target_username: Optional[str] = None,
    audience_type: str = "global",
    audience_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    score: Optional[float] = None,
    created_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    normalized_event_type = (event_type or "").strip() or "generic"
    normalized_audience = (audience_type or "global").lower()
    if normalized_audience not in FEED_AUDIENCE_TYPES:
        normalized_audience = "global"

    audience_id_value: Optional[str] = None
    if normalized_audience == "user":
        derived = target_username if audience_id is None else audience_id
        audience_id_value = (str(derived).strip() or None)
    elif normalized_audience == "server":
        derived = server_slug if audience_id is None else audience_id
        audience_id_value = (str(derived).strip() or None)
        if audience_id_value and server_slug is None:
            server_slug = audience_id_value

    if normalized_audience in {"user", "server"} and not audience_id_value:
        normalized_audience = "global"

    target_username_value = (str(target_username).strip() or None) if target_username else None
    server_slug_value = (str(server_slug).strip() or None) if server_slug else None
    entity_type_value = (str(entity_type).strip() or None) if entity_type else None
    entity_id_value = (str(entity_id).strip() or None) if entity_id else None
    actor_value = (str(actor_username).strip() or None) if actor_username else None
    payload_json = _dump_json(payload) if isinstance(payload, (dict, list)) else _dump_json(payload or {})

    timestamp = created_at or datetime.now()
    base_score = _default_feed_score(normalized_event_type)
    try:
        score_value = float(score) if score is not None else base_score
    except (TypeError, ValueError):
        score_value = base_score

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT INTO feed_events (
                event_type,
                actor_username,
                entity_type,
                entity_id,
                server_slug,
                target_username,
                audience_type,
                audience_id,
                payload,
                score,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                normalized_event_type,
                actor_value,
                entity_type_value,
                entity_id_value,
                server_slug_value,
                target_username_value,
                normalized_audience,
                audience_id_value,
                payload_json,
                score_value,
                timestamp,
            ),
        )
        event_id = c.lastrowid
        conn.commit()

    return _serialize_feed_event_row(
        (
            event_id,
            normalized_event_type,
            actor_value,
            entity_type_value,
            entity_id_value,
            server_slug_value,
            target_username_value,
            normalized_audience,
            audience_id_value,
            payload_json,
            score_value,
            timestamp,
        )
    )


@log_errors()
def get_home_feed(username: Optional[str], limit: int = 30, offset: int = 0) -> Dict[str, Any]:
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 30
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0

    conditions: List[str] = ["audience_type = 'global'"]
    params: List[Any] = []

    if username:
        conditions.append("(audience_type = 'user' AND audience_id = ?)")
        params.append(username)
        memberships = list_user_servers(username, status_filter="active", limit=200)
        server_slugs = sorted(
            {server["slug"] for server in memberships if server.get("slug")}
        )
    else:
        server_slugs = []

    if server_slugs:
        placeholders = ",".join("?" for _ in server_slugs)
        conditions.append(f"(audience_type = 'server' AND audience_id IN ({placeholders}))")
        params.extend(server_slugs)

    where_clause = " OR ".join(conditions)

    count_params = list(params)

    count_query = f"SELECT COUNT(*) FROM feed_events WHERE {where_clause}"

    query = f"""
        SELECT
            id,
            event_type,
            actor_username,
            entity_type,
            entity_id,
            server_slug,
            target_username,
            audience_type,
            audience_id,
            payload,
            score,
            created_at
        FROM feed_events
        WHERE {where_clause}
        ORDER BY score DESC, created_at DESC
        LIMIT ? OFFSET ?
    """

    data_params = list(params) + [limit, offset]

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(count_query, tuple(count_params))
        count_row = c.fetchone()
        total = int(count_row[0]) if count_row else 0

        c.execute(query, tuple(data_params))
        rows = c.fetchall()

    events = [_serialize_feed_event_row(row) for row in rows]
    events.sort(key=lambda item: item.get("computed_score", item.get("score", 0.0)), reverse=True)

    recommended_appended = 0
    if username and len(events) < limit:
        existing_slugs = {slug for slug in server_slugs}
        existing_slugs.update(event.get("server_slug") for event in events if event.get("server_slug"))
        rec_limit = max(0, min(5, limit - len(events)))
        if rec_limit:
            recommended_servers = get_recommended_servers(username, limit=rec_limit + len(existing_slugs))
            recommendation_events: List[Dict[str, Any]] = []
            for server in recommended_servers:
                slug = server.get("slug")
                if not slug or slug in existing_slugs:
                    continue
                recommendation_events.append(_build_server_recommendation_event(username, server))
                existing_slugs.add(slug)
                if len(events) + len(recommendation_events) >= limit:
                    break
            if recommendation_events:
                events.extend(recommendation_events)
                recommended_appended = len(recommendation_events)
                events.sort(key=lambda item: item.get("computed_score", item.get("score", 0.0)), reverse=True)

    next_offset = offset + limit if offset + limit < total else None

    return {
        "events": events,
        "meta": {
            "limit": limit,
            "offset": offset,
            "next_offset": next_offset,
            "server_slugs": server_slugs,
            "includes_user_scope": bool(username),
            "total": total,
            "recommended_appended": recommended_appended,
        },
    }


@log_errors()
def get_server_feed(server_slug: str, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM feed_events WHERE audience_type = 'server' AND audience_id = ?",
            (server_slug,),
        )
        count_row = c.fetchone()
        total = int(count_row[0]) if count_row else 0

        c.execute(
            """
            SELECT
                id,
                event_type,
                actor_username,
                entity_type,
                entity_id,
                server_slug,
                target_username,
                audience_type,
                audience_id,
                payload,
                score,
                created_at
            FROM feed_events
            WHERE audience_type = 'server' AND audience_id = ?
            ORDER BY score DESC, created_at DESC
            LIMIT ? OFFSET ?
        """,
            (server_slug, limit, offset),
        )
        rows = c.fetchall()

    events = [_serialize_feed_event_row(row) for row in rows]
    events.sort(key=lambda item: item.get("computed_score", item.get("score", 0.0)), reverse=True)
    next_offset = offset + limit if offset + limit < total else None

    return {
        "events": events,
        "meta": {
            "limit": limit,
            "offset": offset,
            "next_offset": next_offset,
            "server_slug": server_slug,
            "total": total,
        },
    }
@log_errors()
def get_server_analytics(server_id: int, days: int = 30) -> Dict[str, Any]:
    window_days = max(1, min(int(days), 365))
    now = datetime.now()
    window_start = now - timedelta(days=window_days)
    window_start_str = _to_datetime_string(window_start)
    seven_days_ago = now - timedelta(days=7)
    seven_days_str = _to_datetime_string(seven_days_ago)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT slug, name, topic_tags, settings
            FROM servers
            WHERE id = ?
        """, (server_id,))
        server_row = c.fetchone()
        if not server_row:
            raise ValueError("Server not found.")
        slug = server_row[0]
        name = server_row[1]
        topics = _load_json(server_row[2], [])
        settings = _load_json(server_row[3], {})

        c.execute("""
            SELECT COUNT(*)
            FROM server_memberships
            WHERE server_id = ?
              AND status = 'active'
        """, (server_id,))
        total_members = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT COUNT(*)
            FROM server_memberships
            WHERE server_id = ?
              AND status = 'active'
              AND joined_at IS NOT NULL
              AND joined_at >= ?
        """, (server_id, window_start_str))
        new_members_window = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT COUNT(*)
            FROM server_memberships
            WHERE server_id = ?
              AND status = 'active'
              AND joined_at IS NOT NULL
              AND joined_at >= ?
        """, (server_id, seven_days_str))
        new_members_last_7 = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT strftime('%Y-%m-%d', joined_at) AS day, COUNT(*)
            FROM server_memberships
            WHERE server_id = ?
              AND status = 'active'
              AND joined_at IS NOT NULL
              AND joined_at >= ?
            GROUP BY day
            ORDER BY day ASC
        """, (server_id, window_start_str))
        member_series = [{"date": row[0], "joins": row[1]} for row in c.fetchall() if row[0]]

        c.execute("""
            SELECT COUNT(*)
            FROM messages m
            JOIN server_channels c ON c.id = m.channel_id
            WHERE c.server_id = ?
              AND m.deleted_at IS NULL
              AND m.created_at >= ?
        """, (server_id, window_start_str))
        message_total = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT COUNT(DISTINCT m.sender_id)
            FROM messages m
            JOIN server_channels c ON c.id = m.channel_id
            WHERE c.server_id = ?
              AND m.deleted_at IS NULL
              AND m.created_at >= ?
        """, (server_id, window_start_str))
        active_senders = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT strftime('%Y-%m-%d', m.created_at) AS day, COUNT(*)
            FROM messages m
            JOIN server_channels c ON c.id = m.channel_id
            WHERE c.server_id = ?
              AND m.deleted_at IS NULL
              AND m.created_at >= ?
            GROUP BY day
            ORDER BY day ASC
        """, (server_id, window_start_str))
        message_series = [{"date": row[0], "messages": row[1]} for row in c.fetchall() if row[0]]

        c.execute("""
            SELECT
                c.id,
                c.name,
                c.slug,
                COUNT(m.id) AS message_count
            FROM server_channels c
            LEFT JOIN messages m
              ON m.channel_id = c.id
             AND m.deleted_at IS NULL
             AND m.created_at >= ?
            WHERE c.server_id = ?
            GROUP BY c.id, c.name, c.slug
            ORDER BY message_count DESC, c.name ASC
            LIMIT 5
        """, (window_start_str, server_id))
        top_channels = [{
            "channel_id": row[0],
            "name": row[1],
            "slug": row[2],
            "message_count": int(row[3] or 0),
        } for row in c.fetchall()]

        c.execute("""
            SELECT settings
            FROM server_channels
            WHERE server_id = ?
        """, (server_id,))
        slow_mode_enabled = 0
        for (settings_json,) in c.fetchall():
            channel_settings = _load_json(settings_json, {})
            if isinstance(channel_settings, dict) and int(channel_settings.get("slow_mode") or 0) > 0:
                slow_mode_enabled += 1

        pattern = f'%\"server_slug\": \"{slug.lower()}\"%'
        c.execute("""
            SELECT COUNT(*)
            FROM reports
            WHERE LOWER(context) LIKE ?
              AND status IN ('pending', 'reviewing')
        """, (pattern,))
        open_reports = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT status, COUNT(*)
            FROM reports
            WHERE LOWER(context) LIKE ?
            GROUP BY status
        """, (pattern,))
        report_status_map = {row[0]: row[1] for row in c.fetchall()}

    analytics = {
        "server": {
            "id": server_id,
            "slug": slug,
            "name": name,
            "topics": topics,
            "settings": settings,
        },
        "timeframe_days": window_days,
        "generated_at": _to_datetime_string(now),
        "members": {
            "total": total_members,
            "new_in_window": new_members_window,
            "new_last_7_days": new_members_last_7,
            "growth_series": member_series,
        },
        "messages": {
            "total": message_total,
            "active_senders": active_senders,
            "series": message_series,
        },
        "channels": {
            "slow_mode_enabled": slow_mode_enabled,
            "top": top_channels,
        },
        "reports": {
            "open_count": open_reports,
            "status_breakdown": report_status_map,
        },
    }
    return analytics


def _normalize_digest_period_days(period_days: Optional[int]) -> int:
    try:
        normalized = int(period_days)
    except (TypeError, ValueError):
        normalized = 7
    return max(1, min(normalized, SERVER_OWNER_DIGEST_MAX_PERIOD_DAYS))
def _server_owner_digest_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    payload = _load_json(row[5], {})
    return {
        "id": row[0],
        "server_id": row[1],
        "owner_username": row[2],
        "period_start": _to_datetime_string(row[3]),
        "period_end": _to_datetime_string(row[4]),
        "payload": payload if isinstance(payload, dict) else {"raw": payload},
        "status": row[6],
        "delivery_channel": row[7],
        "created_at": _to_datetime_string(row[8]),
        "delivered_at": _to_datetime_string(row[9]),
        "failure_reason": row[10],
    }


def _compose_digest_highlights(new_members: int, message_total: int, open_reports_total: int) -> List[str]:
    highlights: List[str] = []
    if new_members:
        highlights.append(f"{new_members} new member{'s' if new_members != 1 else ''} joined")
    if message_total:
        highlights.append(f"{message_total} messages were shared")
    if open_reports_total:
        highlights.append(
            f"{open_reports_total} report{'s are' if open_reports_total != 1 else ' is'} awaiting review"
        )
    if not highlights:
        highlights.append("Quiet week — no major changes recorded.")
    return highlights


def _digest_member_detail_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {
        "username": row[0],
        "display_name": row[1] or row[0],
        "joined_at": _to_datetime_string(row[2]),
    }


def _digest_channel_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {
        "channel_id": row[0],
        "name": row[1],
        "slug": row[2],
        "message_count": int(row[3] or 0),
    }


def _digest_contributor_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    return {
        "username": row[0],
        "display_name": row[1] or row[0],
        "message_count": int(row[2] or 0),
    }


def _digest_report_row(row: Tuple[Any, ...]) -> Dict[str, Any]:
    context = _load_json(row[2], {})
    return {
        "id": row[0],
        "status": row[1],
        "context": context,
        "created_at": _to_datetime_string(row[3]),
    }


@log_errors()
def compute_server_owner_digest(
    server_id: int,
    owner_username: Optional[str] = None,
    *,
    period_days: int = 7,
) -> Dict[str, Any]:
    period_days_normalized = _normalize_digest_period_days(period_days)
    now = datetime.now()
    period_end = now
    period_start = now - timedelta(days=period_days_normalized)
    period_start_str = _to_datetime_string(period_start)
    period_end_str = _to_datetime_string(period_end)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT owner_username, slug, name, topic_tags, settings
            FROM servers
            WHERE id = ?
        """, (server_id,))
        server_row = c.fetchone()
        if not server_row:
            raise ValueError("Server not found.")
        server_owner = server_row[0]
        server_slug = server_row[1]
        server_name = server_row[2]
        server_topics = _load_json(server_row[3], [])
        server_settings = _load_json(server_row[4], {})

        if owner_username and owner_username != server_owner:
            raise ValueError("Owner username does not match server owner.")
        owner_username = owner_username or server_owner

        c.execute("""
            SELECT COUNT(*)
            FROM server_memberships
            WHERE server_id = ?
              AND status = 'active'
              AND joined_at IS NOT NULL
              AND joined_at >= ?
        """, (server_id, period_start_str))
        new_members_count = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT sm.username,
                   COALESCE(p.display_name, sm.username),
                   sm.joined_at
            FROM server_memberships sm
            LEFT JOIN profiles p ON p.username = sm.username
            WHERE sm.server_id = ?
              AND sm.status = 'active'
              AND sm.joined_at IS NOT NULL
              AND sm.joined_at >= ?
            ORDER BY sm.joined_at DESC
            LIMIT 10
        """, (server_id, period_start_str))
        new_member_details = [_digest_member_detail_row(row) for row in c.fetchall()]

        c.execute("""
            SELECT COUNT(*)
            FROM messages m
            JOIN server_channels sc ON sc.id = m.channel_id
            WHERE sc.server_id = ?
              AND m.deleted_at IS NULL
              AND m.created_at >= ?
        """, (server_id, period_start_str))
        message_total = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT COUNT(DISTINCT m.sender_id)
            FROM messages m
            JOIN server_channels sc ON sc.id = m.channel_id
            WHERE sc.server_id = ?
              AND m.deleted_at IS NULL
              AND m.created_at >= ?
        """, (server_id, period_start_str))
        active_senders = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT
                sc.id,
                sc.name,
                sc.slug,
                COUNT(m.id) AS message_count
            FROM server_channels sc
            LEFT JOIN messages m
              ON m.channel_id = sc.id
             AND m.deleted_at IS NULL
             AND m.created_at >= ?
            WHERE sc.server_id = ?
            GROUP BY sc.id, sc.name, sc.slug
            ORDER BY message_count DESC, sc.name ASC
            LIMIT 3
        """, (period_start_str, server_id))
        top_channels = [_digest_channel_row(row) for row in c.fetchall()]

        c.execute("""
            SELECT
                m.sender_id,
                COALESCE(p.display_name, m.sender_id) AS display_name,
                COUNT(*) AS message_count
            FROM messages m
            JOIN server_channels sc ON sc.id = m.channel_id
            LEFT JOIN profiles p ON p.display_name = m.sender_id
            WHERE sc.server_id = ?
              AND m.deleted_at IS NULL
              AND m.created_at >= ?
            GROUP BY m.sender_id, display_name
            ORDER BY message_count DESC, display_name ASC
            LIMIT 5
        """, (server_id, period_start_str))
        top_contributors = [_digest_contributor_row(row) for row in c.fetchall()]

        report_pattern = f'%\\"server_slug\\": \\"{server_slug.lower()}\\"%'
        c.execute("""
            SELECT COUNT(*)
            FROM reports
            WHERE LOWER(context) LIKE ?
              AND status IN ('pending', 'reviewing')
        """, (report_pattern,))
        open_reports_total = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT COUNT(*)
            FROM reports
            WHERE LOWER(context) LIKE ?
              AND status IN ('pending', 'reviewing')
              AND created_at >= ?
        """, (report_pattern, period_start_str))
        new_reports_in_period = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT id, status, context, created_at
            FROM reports
            WHERE LOWER(context) LIKE ?
              AND status IN ('pending', 'reviewing')
            ORDER BY created_at ASC
            LIMIT 5
        """, (report_pattern,))
        open_report_details = [_digest_report_row(row) for row in c.fetchall()]

        c.execute("""
            SELECT COUNT(*)
            FROM server_memberships
            WHERE server_id = ?
              AND status = 'active'
        """, (server_id,))
        total_active_members = int(c.fetchone()[0] or 0)

    analytics_snapshot = get_server_analytics(server_id, days=period_days_normalized)

    highlights = _compose_digest_highlights(new_members_count, message_total, open_reports_total)
    summary_text = " • ".join(highlights)

    digest = {
        "server": {
            "id": server_id,
            "slug": server_slug,
            "name": server_name,
            "topics": server_topics if isinstance(server_topics, list) else [],
            "settings": server_settings if isinstance(server_settings, dict) else {},
        },
        "owner_username": owner_username,
        "period": {
            "days": period_days_normalized,
            "start": period_start_str,
            "end": period_end_str,
        },
        "generated_at": _to_datetime_string(now),
        "metrics": {
            "members": {
                "total_active": total_active_members,
                "new_count": new_members_count,
                "new_members": new_member_details,
            },
            "messages": {
                "total": message_total,
                "active_senders": active_senders,
                "top_channels": top_channels,
                "top_contributors": top_contributors,
            },
            "reports": {
                "open_total": open_reports_total,
                "new_in_period": new_reports_in_period,
                "open_details": open_report_details,
            },
        },
        "analytics_snapshot": analytics_snapshot,
        "highlights": highlights,
        "summary": summary_text,
    }
    return digest


@log_errors()
def enqueue_server_owner_digest(
    server_id: int,
    owner_username: Optional[str] = None,
    *,
    period_days: int = 7,
    delivery_channel: str = SERVER_OWNER_DIGEST_DEFAULT_CHANNEL,
) -> Dict[str, Any]:
    digest_payload = compute_server_owner_digest(
        server_id,
        owner_username=owner_username,
        period_days=period_days,
    )
    payload_json = _dump_json(digest_payload)

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO server_owner_digests (
                server_id,
                owner_username,
                period_start,
                period_end,
                payload,
                status,
                delivery_channel
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            server_id,
            digest_payload["owner_username"],
            digest_payload["period"]["start"],
            digest_payload["period"]["end"],
            payload_json,
            SERVER_OWNER_DIGEST_STATUS_PENDING,
            delivery_channel or SERVER_OWNER_DIGEST_DEFAULT_CHANNEL,
        ))
        digest_id = c.lastrowid
        conn.commit()

        c.execute("""
            SELECT
                id,
                server_id,
                owner_username,
                period_start,
                period_end,
                payload,
                status,
                delivery_channel,
                created_at,
                delivered_at,
                failure_reason
            FROM server_owner_digests
            WHERE id = ?
        """, (digest_id,))
        row = c.fetchone()

    return _server_owner_digest_row_to_dict(row) if row else {}


@log_errors()
def list_server_owner_digests(
    server_id: int,
    *,
    limit: int = 20,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    status_filtered = status if status in SERVER_OWNER_DIGEST_STATUSES else None

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if status_filtered:
            c.execute("""
                SELECT
                    id,
                    server_id,
                    owner_username,
                    period_start,
                    period_end,
                    payload,
                    status,
                    delivery_channel,
                    created_at,
                    delivered_at,
                    failure_reason
                FROM server_owner_digests
                WHERE server_id = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (server_id, status_filtered, limit))
        else:
            c.execute("""
                SELECT
                    id,
                    server_id,
                    owner_username,
                    period_start,
                    period_end,
                    payload,
                    status,
                    delivery_channel,
                    created_at,
                    delivered_at,
                    failure_reason
                FROM server_owner_digests
                WHERE server_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (server_id, limit))
        rows = c.fetchall()

    return [_server_owner_digest_row_to_dict(row) for row in rows]


@log_errors()
def get_pending_owner_digests(limit: int = 50) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT
                id,
                server_id,
                owner_username,
                period_start,
                period_end,
                payload,
                status,
                delivery_channel,
                created_at,
                delivered_at,
                failure_reason
            FROM server_owner_digests
            WHERE status = ?
            ORDER BY created_at ASC
            LIMIT ?
        """, (SERVER_OWNER_DIGEST_STATUS_PENDING, limit))
        rows = c.fetchall()
    return [_server_owner_digest_row_to_dict(row) for row in rows]


@log_errors()
def mark_server_owner_digest_delivered(
    digest_id: int,
    *,
    success: bool = True,
    failure_reason: Optional[str] = None,
) -> Dict[str, Any]:
    if not digest_id:
        raise ValueError("Digest id is required.")
    status = SERVER_OWNER_DIGEST_STATUS_DELIVERED if success else SERVER_OWNER_DIGEST_STATUS_FAILED
    delivered_at = datetime.now() if success else None

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if success:
            c.execute("""
                UPDATE server_owner_digests
                SET status = ?,
                    delivered_at = ?,
                    failure_reason = NULL
                WHERE id = ?
            """, (status, delivered_at, digest_id))
        else:
            c.execute("""
                UPDATE server_owner_digests
                SET status = ?,
                    failure_reason = ?
                WHERE id = ?
            """, (status, failure_reason, digest_id))
        if c.rowcount == 0:
            raise ValueError("Digest record not found.")
        conn.commit()

        c.execute("""
            SELECT
                id,
                server_id,
                owner_username,
                period_start,
                period_end,
                payload,
                status,
                delivery_channel,
                created_at,
                delivered_at,
                failure_reason
            FROM server_owner_digests
            WHERE id = ?
        """, (digest_id,))
        row = c.fetchone()

    return _server_owner_digest_row_to_dict(row) if row else {}


@log_errors()
def get_server_owner_digest_preview(
    server_id: int,
    owner_username: Optional[str] = None,
    *,
    period_days: int = 7,
) -> Dict[str, Any]:
    return compute_server_owner_digest(
        server_id,
        owner_username=owner_username,
        period_days=period_days,
    )


@log_errors()
def get_community_analytics(days: int = 30) -> Dict[str, Any]:
    window_days = max(1, min(int(days), 365))
    now = datetime.now()
    window_start = now - timedelta(days=window_days)
    window_start_str = _to_datetime_string(window_start)

    with get_pool().get_connection() as conn:
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM servers")
        total_servers = int(c.fetchone()[0] or 0)

        c.execute("SELECT COUNT(*) FROM servers WHERE created_at >= ?", (window_start_str,))
        new_servers = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT COUNT(DISTINCT c.server_id)
            FROM messages m
            JOIN server_channels c ON c.id = m.channel_id
            WHERE m.deleted_at IS NULL
              AND m.created_at >= ?
        """, (window_start_str,))
        active_servers = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT COUNT(*)
            FROM server_memberships
            WHERE status = 'active'
        """)
        total_memberships = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT COUNT(*)
            FROM server_memberships
            WHERE status = 'active'
              AND joined_at IS NOT NULL
              AND joined_at >= ?
        """, (window_start_str,))
        new_memberships = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT COUNT(*)
            FROM messages m
            JOIN server_channels c ON c.id = m.channel_id
            WHERE m.deleted_at IS NULL
              AND m.created_at >= ?
        """, (window_start_str,))
        message_total = int(c.fetchone()[0] or 0)

        c.execute("""
            SELECT status, COUNT(*)
            FROM reports
            GROUP BY status
        """)
        report_counts = {row[0]: row[1] for row in c.fetchall()}
        open_reports = report_counts.get(REPORT_STATUS_PENDING, 0) + report_counts.get(REPORT_STATUS_REVIEWING, 0)

        c.execute("SELECT topic_tags FROM servers")
        tag_counter: Dict[str, int] = {}
        for (topic_json,) in c.fetchall():
            topics = _load_json(topic_json, [])
            if not isinstance(topics, list):
                continue
            for item in topics:
                if isinstance(item, dict):
                    label = item.get("label") or item.get("slug") or item.get("id")
                else:
                    label = str(item)
                if not label:
                    continue
                key = label.strip()
                if not key:
                    continue
                tag_counter[key] = tag_counter.get(key, 0) + 1
        top_topics = sorted(
            [{"label": label, "count": count} for label, count in tag_counter.items()],
            key=lambda entry: entry["count"],
            reverse=True,
        )[:10]

    analytics = {
        "timeframe_days": window_days,
        "generated_at": _to_datetime_string(now),
        "servers": {
            "total": total_servers,
            "new_in_window": new_servers,
            "active_in_window": active_servers,
        },
        "memberships": {
            "total_active": total_memberships,
            "new_in_window": new_memberships,
        },
        "messages": {
            "total_in_window": message_total,
        },
        "reports": {
            "open": open_reports,
            "status_breakdown": report_counts,
        },
        "top_topics": top_topics,
    }
    return analytics


@log_errors()
def increment_listing_premium_impression(listing_id: int) -> None:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE listing_analytics
            SET premium_impressions = COALESCE(premium_impressions, 0) + 1
            WHERE listing_id = ?
        """, (listing_id,))
        if c.rowcount == 0:
            c.execute("""
                INSERT INTO listing_analytics (listing_id, premium_impressions, premium_clicks, created_at)
                VALUES (?, 1, 0, ?)
            """, (listing_id, datetime.now()))
        conn.commit()


@log_errors()
def increment_listing_premium_click(listing_id: int) -> None:
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE listing_analytics
            SET premium_clicks = COALESCE(premium_clicks, 0) + 1
            WHERE listing_id = ?
        """, (listing_id,))
        if c.rowcount == 0:
            c.execute("""
                INSERT INTO listing_analytics (listing_id, premium_impressions, premium_clicks, created_at)
                VALUES (?, 0, 1, ?)
            """, (listing_id, datetime.now()))
        conn.commit()
def save_listing(title, price, link, image_url=None, source=None, user_id=None,
                 *, premium_placement: int = 0, premium_until: Optional[datetime] = None):
    """Save a listing to the database"""
    is_new_listing = False
    listing_id = None
    
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        try:
            # Use a transaction to ensure atomicity
            # First, try to insert the listing
            now = datetime.now()
            c.execute("""
                INSERT OR IGNORE INTO listings (title, price, link, image_url, source, created_at, premium_placement, premium_until, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (title, price, link, image_url, source, now, premium_placement, premium_until, user_id))
            
            # Check if we got a new row (lastrowid > 0 means successful insert)
            listing_id = c.lastrowid
            if listing_id > 0:
                # New listing was successfully inserted
                is_new_listing = True
            else:
                # Insert was ignored (duplicate), update existing record with latest data
                c.execute("SELECT id FROM listings WHERE link = ?", (link,))
                existing = c.fetchone()
                if existing:
                    listing_id = existing[0]
                    c.execute(
                        """
                        UPDATE listings
                        SET title = ?, price = ?, image_url = ?, source = ?, created_at = ?, premium_placement = ?, premium_until = ?, user_id = COALESCE(?, user_id)
                        WHERE id = ?
                        """,
                        (title, price, image_url, source, now, premium_placement, premium_until, user_id, listing_id),
                    )
                else:
                    # This shouldn't happen, but handle it gracefully
                    logger.warning(f"Failed to insert listing and couldn't find existing: {link}")
                    conn.rollback()
                    return None
            
            conn.commit()
            
        except Exception as e:
            logger.error(f"Error saving listing: {e}")
            conn.rollback()
            return None
        
        # Save analytics data if we have a valid listing ID
        if listing_id and is_new_listing:
            try:
                # Extract keywords from title
                title_lower = title.lower()
                car_keywords = ['firebird', 'camaro', 'corvette', 'mustang', 'charger', 'challenger', 
                               'trans am', 'gto', 'nova', 'chevelle', 'impala', 'monte carlo']
                
                for keyword in car_keywords:
                    if keyword in title_lower:
                        # Determine price range (inclusive boundaries)
                        if price <= 5000:
                            price_range = "Under $5K"
                        elif price <= 10000:
                            price_range = "$5K-$10K"
                        elif price <= 20000:
                            price_range = "$10K-$20K"
                        elif price <= 30000:
                            price_range = "$20K-$30K"
                        else:
                            price_range = "Over $30K"
                        
                        # Determine category
                        category = "Classic Cars" if any(k in title_lower for k in ['firebird', 'camaro', 'corvette', 'trans am', 'gto', 'nova', 'chevelle', 'impala', 'monte carlo']) else "Modern Cars"
                        
                        save_listing_analytics(listing_id, keyword, category, price_range, source)
            except Exception as e:
                logger.error(f"Error saving analytics for listing {listing_id}: {e}")
        
        if listing_id and is_new_listing:
            try:
                listing_payload = {
                    "id": listing_id,
                    "title": title,
                    "price": price,
                    "link": link,
                    "image_url": image_url,
                    "source": source,
                    "created_at": _to_datetime_string(now),
                }
                log_feed_event(
                    event_type="listing_alert",
                    actor_username=user_id,
                    entity_type="listing",
                    entity_id=str(listing_id),
                    audience_type="global",
                    payload=listing_payload,
                    score=4.0,
                )
            except Exception as feed_exc:
                logger.warning(f"Failed to log listing feed event for {listing_id}: {feed_exc}")

        # Send notifications for new listings
        if is_new_listing:
            try:
                # Import here to avoid circular imports
                from notifications import notify_new_listing
                
                # Get all users with notifications enabled
                users = get_users_with_notifications_enabled()
                
                # Track notification results
                notification_results = {
                    'total': len(users),
                    'success': 0,
                    'failed': 0,
                    'failed_users': []
                }
                
                # Send notifications to each user
                for user in users:
                    try:
                        notify_new_listing(
                            user_email=user['email'],
                            user_phone=user['phone_number'],
                            email_enabled=user['email_notifications'],
                            sms_enabled=user['sms_notifications'],
                            listing_title=title,
                            listing_price=price,
                            listing_url=link,
                            listing_source=source or 'unknown'
                        )
                        notification_results['success'] += 1
                    except Exception as e:
                        notification_results['failed'] += 1
                        notification_results['failed_users'].append(user['username'])
                        logger.error(f"Error sending notification to user {user['username']}: {e}")
                        # Continue to next user even if one fails
                
                # Log summary
                if notification_results['failed'] > 0:
                    logger.warning(f"Notification summary for listing {listing_id}: {notification_results['success']}/{notification_results['total']} succeeded. Failed for: {', '.join(notification_results['failed_users'])}")
                else:
                    logger.info(f"All {notification_results['success']} notifications sent successfully for listing {listing_id}")
                        
            except Exception as e:
                logger.error(f"Error processing notifications for listing {listing_id}: {e}")
                # Don't fail the listing save if notifications fail
        
        if listing_id:
            return get_listing_by_id(listing_id)
        return None


@log_errors()
def get_listings(limit=100, user_id=None):
    """Get listings from database, optionally filtered by user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if user_id:
            c.execute("""
                SELECT id, title, price, link, image_url, source, created_at 
                FROM listings 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (user_id, limit))
        else:
            c.execute("""
                SELECT id, title, price, link, image_url, source, created_at 
                FROM listings 
                ORDER BY created_at DESC 
                LIMIT ?
            """, (limit,))
        rows = c.fetchall()
        return rows
@log_errors()
def get_listing_by_id(listing_id: int) -> Optional[Dict[str, Any]]:
    """Return a single listing by ID."""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, title, price, link, image_url, source, created_at
            FROM listings
            WHERE id = ?
        """, (listing_id,))
        row = c.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "title": row[1],
        "price": row[2],
        "link": row[3],
        "image_url": row[4],
        "source": row[5],
        "created_at": _to_datetime_string(row[6]),
    }


@log_errors()
def get_listing_count(user_id=None):
    """Get total number of listings, optionally for a specific user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if user_id:
            c.execute("SELECT COUNT(*) FROM listings WHERE user_id = ?", (user_id,))
        else:
            c.execute("SELECT COUNT(*) FROM listings")
        count = c.fetchone()[0]
        return count


@log_errors()
def get_listings_paginated(limit=50, offset=0, user_id=None):
    """Get paginated listings with offset"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if user_id:
            c.execute("""
                SELECT id, title, price, link, image_url, source, created_at 
                FROM listings 
                WHERE user_id = ?
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (user_id, limit, offset))
        else:
            c.execute("""
                SELECT id, title, price, link, image_url, source, created_at 
                FROM listings 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
        rows = c.fetchall()
        return rows


# ======================
# ANALYTICS FUNCTIONS (from original db.py)
# ======================

@log_errors()
def save_listing_analytics(listing_id, keyword, category, price_range, source):
    """Save analytics data for a listing"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO listing_analytics (listing_id, keyword, category, price_range, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (listing_id, keyword, category, price_range, source, datetime.now()))
        conn.commit()


@log_errors()
def get_keyword_trends(days=30, keyword=None, user_id=None):
    """Get keyword trends over time"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if keyword:
            c.execute("""
                SELECT date, keyword, count, avg_price, source
                FROM keyword_trends 
                WHERE date >= date('now', ? || ' days')
                  AND keyword = ?
                  AND user_id = ?
                ORDER BY date DESC
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT date, keyword, count, avg_price, source
                FROM keyword_trends 
                WHERE date >= date('now', ? || ' days')
                  AND user_id = ?
                ORDER BY date DESC, count DESC
            """, (f'-{days}', user_id))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_price_analytics(days=30, source=None, keyword=None, user_id=None):
    """Get price analytics over time"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Build query with optional filters
        if keyword and source:
            c.execute("""
                SELECT DATE(l.created_at) as date, 
                       COUNT(*) as count,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       l.source
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND l.source = ?
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY DATE(l.created_at), l.source
                ORDER BY date DESC
            """, (f'-{days}', source, keyword, user_id))
        elif keyword:
            c.execute("""
                SELECT DATE(l.created_at) as date, 
                       COUNT(*) as count,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       l.source
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY DATE(l.created_at), l.source
                ORDER BY date DESC
            """, (f'-{days}', keyword, user_id))
        elif source:
            c.execute("""
                SELECT DATE(created_at) as date, 
                       COUNT(*) as count,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       source
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND source = ?
                  AND user_id = ?
                GROUP BY DATE(created_at), source
                ORDER BY date DESC
            """, (f'-{days}', source, user_id))
        else:
            c.execute("""
                SELECT DATE(created_at) as date, 
                       COUNT(*) as count,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       source
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
                GROUP BY DATE(created_at), source
                ORDER BY date DESC
            """, (f'-{days}', user_id))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_source_comparison(days=30, keyword=None, user_id=None):
    """Compare performance across different sources"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if keyword:
            c.execute("""
                SELECT l.source,
                       COUNT(*) as total_listings,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       COUNT(DISTINCT DATE(l.created_at)) as active_days
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY l.source
                ORDER BY total_listings DESC
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT source,
                       COUNT(*) as total_listings,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       COUNT(DISTINCT DATE(created_at)) as active_days
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
                GROUP BY source
                ORDER BY total_listings DESC
            """, (f'-{days}', user_id))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_keyword_analysis(days=30, limit=20, keyword=None, user_id=None):
    """Get top keywords and their performance"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if keyword:
            # Return only the specified keyword
            c.execute("""
                SELECT la.keyword,
                       COUNT(*) as frequency,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       COUNT(DISTINCT la.source) as sources_count
                FROM listing_analytics la
                JOIN listings l ON la.listing_id = l.id
                WHERE la.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY la.keyword
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT la.keyword,
                       COUNT(*) as frequency,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       COUNT(DISTINCT la.source) as sources_count
                FROM listing_analytics la
                JOIN listings l ON la.listing_id = l.id
                WHERE la.created_at >= datetime('now', ? || ' days')
                  AND l.user_id = ?
                GROUP BY la.keyword
                ORDER BY frequency DESC
                LIMIT ?
            """, (f'-{days}', user_id, limit))
        
        rows = c.fetchall()
        return rows


@log_errors()
def get_hourly_activity(days=7, keyword=None, user_id=None):
    """Get listing activity by hour of day"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        if keyword:
            c.execute("""
                SELECT strftime('%H', l.created_at) as hour,
                       COUNT(*) as count,
                       l.source
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY strftime('%H', l.created_at), l.source
                ORDER BY hour
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT strftime('%H', created_at) as hour,
                       COUNT(*) as count,
                       source
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
                GROUP BY strftime('%H', created_at), source
                ORDER BY hour
            """, (f'-{days}', user_id))
        
        rows = c.fetchall()
        return rows
@log_errors()
def get_price_distribution(days=30, bins=10, keyword=None, user_id=None):
    """Get price distribution data for histograms"""
    # Validate bins parameter to prevent division by zero
    if bins <= 0:
        logger.warning(f"Invalid bins parameter: {bins}, using default of 10")
        bins = 10
    
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Get min and max prices with optional keyword filter
        if keyword:
            c.execute("""
                SELECT MIN(l.price) as min_price, MAX(l.price) as max_price
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND l.price > 0
                  AND la.keyword = ?
                  AND l.user_id = ?
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT MIN(price) as min_price, MAX(price) as max_price
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND price > 0
                  AND user_id = ?
            """, (f'-{days}', user_id))
        
        result = c.fetchone()
        if not result or not result[0] or not result[1]:
            return []
        
        min_price, max_price = result
        
        # Handle edge case: all listings have the same price
        if min_price == max_price:
            return [{
                'range': f"${min_price:.0f}",
                'count': 1,
                'start': min_price,
                'end': max_price
            }]
        
        # Calculate bin size (bins is already validated to be > 0)
        bin_size = (max_price - min_price) / bins
        
        # Additional safety check
        if bin_size <= 0:
            logger.warning("Invalid bin_size calculated, returning empty distribution")
            return []
        
        price_ranges = []
        for i in range(bins):
            start = min_price + (i * bin_size)
            end = min_price + ((i + 1) * bin_size)
            
            # For the last bin, include the maximum price (fix off-by-one error)
            is_last_bin = (i == bins - 1)
            
            if keyword:
                if is_last_bin:
                    c.execute("""
                        SELECT COUNT(*) as count
                        FROM listings l
                        JOIN listing_analytics la ON l.id = la.listing_id
                        WHERE l.created_at >= datetime('now', ? || ' days')
                          AND l.price >= ? AND l.price <= ?
                          AND la.keyword = ?
                          AND l.user_id = ?
                    """, (f'-{days}', start, end, keyword, user_id))
                else:
                    c.execute("""
                        SELECT COUNT(*) as count
                        FROM listings l
                        JOIN listing_analytics la ON l.id = la.listing_id
                        WHERE l.created_at >= datetime('now', ? || ' days')
                          AND l.price >= ? AND l.price < ?
                          AND la.keyword = ?
                          AND l.user_id = ?
                    """, (f'-{days}', start, end, keyword, user_id))
            else:
                if is_last_bin:
                    c.execute("""
                        SELECT COUNT(*) as count
                        FROM listings 
                        WHERE created_at >= datetime('now', ? || ' days')
                          AND price >= ? AND price <= ?
                          AND user_id = ?
                    """, (f'-{days}', start, end, user_id))
                else:
                    c.execute("""
                        SELECT COUNT(*) as count
                        FROM listings 
                        WHERE created_at >= datetime('now', ? || ' days')
                          AND price >= ? AND price < ?
                          AND user_id = ?
                    """, (f'-{days}', start, end, user_id))
            
            count = c.fetchone()[0]
            price_ranges.append({
                'range': f"${start:.0f}-${end:.0f}",
                'count': count,
                'start': start,
                'end': end
            })
        
        return price_ranges


@log_errors()
def update_keyword_trends(user_id=None):
    """Update keyword trends from recent listings"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Get recent listings and extract keywords
        if user_id:
            c.execute("""
                SELECT id, title, price, source, created_at, user_id
                FROM listings 
                WHERE created_at >= datetime('now', '-1 day')
                  AND user_id = ?
            """, (user_id,))
        else:
            c.execute("""
                SELECT id, title, price, source, created_at, user_id
                FROM listings 
                WHERE created_at >= datetime('now', '-1 day')
            """)
        
        listings = c.fetchall()
        
        # Simple keyword extraction - group by user_id
        user_keywords = {}
        for listing in listings:
            listing_id, title, price, source, created_at, listing_user_id = listing
            title_lower = title.lower()
            
            if listing_user_id not in user_keywords:
                user_keywords[listing_user_id] = {}
            
            car_keywords = ['firebird', 'camaro', 'corvette', 'mustang', 'charger', 'challenger', 
                           'trans am', 'gto', 'nova', 'chevelle', 'impala', 'monte carlo']
            
            for keyword in car_keywords:
                if keyword in title_lower:
                    if keyword not in user_keywords[listing_user_id]:
                        user_keywords[listing_user_id][keyword] = {'count': 0, 'total_price': 0, 'sources': set()}
                    user_keywords[listing_user_id][keyword]['count'] += 1
                    user_keywords[listing_user_id][keyword]['total_price'] += price
                    user_keywords[listing_user_id][keyword]['sources'].add(source)
        
        # Save keyword trends per user
        today = datetime.now().date()
        for listing_user_id, keywords in user_keywords.items():
            for keyword, data in keywords.items():
                avg_price = data['total_price'] / data['count']
                for source in data['sources']:
                    c.execute("""
                        INSERT OR REPLACE INTO keyword_trends (keyword, count, avg_price, date, source, user_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (keyword, data['count'], avg_price, today, source, listing_user_id))
        
        conn.commit()


@log_errors()
def get_market_insights(days=30, keyword=None, user_id=None):
    """Get comprehensive market insights"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Build query with optional keyword filter
        if keyword:
            # Overall stats with keyword filter
            c.execute("""
                SELECT COUNT(*) as total_listings,
                       AVG(l.price) as avg_price,
                       MIN(l.price) as min_price,
                       MAX(l.price) as max_price,
                       COUNT(DISTINCT l.source) as sources_count
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
            """, (f'-{days}', keyword, user_id))
        else:
            # Overall stats without filter
            c.execute("""
                SELECT COUNT(*) as total_listings,
                       AVG(price) as avg_price,
                       MIN(price) as min_price,
                       MAX(price) as max_price,
                       COUNT(DISTINCT source) as sources_count
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
            """, (f'-{days}', user_id))
        
        overall_stats = c.fetchone()
        
        # Top performing keywords
        if keyword:
            c.execute("""
                SELECT la.keyword, COUNT(*) as count, AVG(l.price) as avg_price
                FROM listing_analytics la
                JOIN listings l ON la.listing_id = l.id
                WHERE la.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY la.keyword
                LIMIT 5
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT la.keyword, COUNT(*) as count, AVG(l.price) as avg_price
                FROM listing_analytics la
                JOIN listings l ON la.listing_id = l.id
                WHERE la.created_at >= datetime('now', ? || ' days')
                  AND l.user_id = ?
                GROUP BY la.keyword
                ORDER BY count DESC
                LIMIT 5
            """, (f'-{days}', user_id))
        
        top_keywords_rows = c.fetchall()
        
        # Source performance
        if keyword:
            c.execute("""
                SELECT l.source, COUNT(*) as count, AVG(l.price) as avg_price
                FROM listings l
                JOIN listing_analytics la ON l.id = la.listing_id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY l.source
                ORDER BY count DESC
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT source, COUNT(*) as count, AVG(price) as avg_price
                FROM listings 
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
                GROUP BY source
                ORDER BY count DESC
            """, (f'-{days}', user_id))
        
        source_rows = c.fetchall()

        # Price distribution buckets
        if keyword:
            c.execute("""
                SELECT
                    CASE
                        WHEN l.price < 5000 THEN 'Under $5K'
                        WHEN l.price < 10000 THEN '$5K-$10K'
                        WHEN l.price < 20000 THEN '$10K-$20K'
                        WHEN l.price < 30000 THEN '$20K-$30K'
                        ELSE 'Over $30K'
                    END AS bucket,
                    COUNT(*) as count
                FROM listings l
                JOIN listing_analytics la ON la.listing_id = l.id
                WHERE l.created_at >= datetime('now', ? || ' days')
                  AND la.keyword = ?
                  AND l.user_id = ?
                GROUP BY bucket
                ORDER BY bucket
            """, (f'-{days}', keyword, user_id))
        else:
            c.execute("""
                SELECT
                    CASE
                        WHEN price < 5000 THEN 'Under $5K'
                        WHEN price < 10000 THEN '$5K-$10K'
                        WHEN price < 20000 THEN '$10K-$20K'
                        WHEN price < 30000 THEN '$20K-$30K'
                        ELSE 'Over $30K'
                    END AS bucket,
                    COUNT(*) as count
                FROM listings
                WHERE created_at >= datetime('now', ? || ' days')
                  AND user_id = ?
                GROUP BY bucket
                ORDER BY bucket
            """, (f'-{days}', user_id))

        price_rows = c.fetchall()

        top_keywords = [
            {
                "keyword": row[0],
                "count": int(row[1] or 0),
                "average_price": float(row[2]) if row[2] is not None else None,
            }
            for row in top_keywords_rows
            if row[0]
        ]

        source_performance = [
            {
                "source": row[0] or "unknown",
                "count": int(row[1] or 0),
                "average_price": float(row[2]) if row[2] is not None else None,
            }
            for row in source_rows
        ]

        price_distribution = [
            {
                "bucket": row[0] or "Unknown",
                "count": int(row[1] or 0),
            }
            for row in price_rows
            if row[0]
        ]

        return {
            "overall_stats": overall_stats,
            "top_keywords": top_keywords,
            "source_performance": source_performance,
            "price_distribution": price_distribution,
        }


# ======================
# SELLER LISTINGS
# ======================

@log_errors()
def create_seller_listing(username, title, description, price, category, location, images, marketplaces, original_cost=None):
    """Create a new seller listing"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO seller_listings (username, title, description, price, original_cost, category, location, images, marketplaces)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, title, description, price, original_cost, category, location, images, marketplaces))
        conn.commit()
        return c.lastrowid


@log_errors()
def get_seller_listings(username=None, status=None, limit=100):
    """Get seller listings for a user or all listings"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        query = "SELECT * FROM seller_listings WHERE 1=1"
        params = []
        
        if username:
            query += " AND username = ?"
            params.append(username)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        c.execute(query, params)
        rows = c.fetchall()
        
        # Convert to list of dicts for easier handling
        columns = [desc[0] for desc in c.description]
        return [dict(zip(columns, row)) for row in rows]


@log_errors()
def get_seller_listing_by_id(listing_id):
    """Get a specific seller listing by ID"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM seller_listings WHERE id = ?", (listing_id,))
        row = c.fetchone()
        if row:
            columns = [desc[0] for desc in c.description]
            return dict(zip(columns, row))
        return None
def update_seller_listing(listing_id, **kwargs):
    """Update a seller listing"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Build update query dynamically based on provided kwargs
        allowed_fields = ['title', 'description', 'price', 'original_cost', 'category', 'location', 'images', 'marketplaces', 'status']
        updates = []
        values = []
        
        for field in allowed_fields:
            if field in kwargs:
                updates.append(f"{field} = ?")
                values.append(kwargs[field])
        
        if not updates:
            return False
        
        # Always update updated_at
        updates.append("updated_at = CURRENT_TIMESTAMP")
        
        query = f"UPDATE seller_listings SET {', '.join(updates)} WHERE id = ?"
        values.append(listing_id)
        
        c.execute(query, values)
        conn.commit()
        return c.rowcount > 0


@log_errors()
def delete_seller_listing(listing_id, username):
    """Delete a seller listing (only if owned by user)"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM seller_listings WHERE id = ? AND username = ?", (listing_id, username))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def update_seller_listing_urls(listing_id, craigslist_url=None, facebook_url=None, ksl_url=None):
    """Update marketplace URLs after posting"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        updates = []
        values = []
        
        if craigslist_url is not None:
            updates.append("craigslist_url = ?")
            values.append(craigslist_url)
        
        if facebook_url is not None:
            updates.append("facebook_url = ?")
            values.append(facebook_url)
        
        if ksl_url is not None:
            updates.append("ksl_url = ?")
            values.append(ksl_url)
        
        if updates:
            updates.append("posted_at = CURRENT_TIMESTAMP")
            updates.append("status = 'posted'")
            query = f"UPDATE seller_listings SET {', '.join(updates)} WHERE id = ?"
            values.append(listing_id)
            
            c.execute(query, values)
            conn.commit()
            return True
        
        return False


@log_errors()
def update_seller_listing_status(listing_id, username, status, sold_on_marketplace=None, actual_sale_price=None):
    """Update the status of a seller listing"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Build update query based on what's being updated
        updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        values = [status]
        
        # If marking as sold, update additional fields
        if status == 'sold':
            updates.append("sold_at = CURRENT_TIMESTAMP")
            if sold_on_marketplace:
                updates.append("sold_on_marketplace = ?")
                values.append(sold_on_marketplace)
            if actual_sale_price is not None:
                updates.append("actual_sale_price = ?")
                values.append(actual_sale_price)
        
        # Add WHERE clause parameters
        values.extend([listing_id, username])
        
        query = f"UPDATE seller_listings SET {', '.join(updates)} WHERE id = ? AND username = ?"
        c.execute(query, values)
        
        conn.commit()
        return c.rowcount > 0


@log_errors()
def get_seller_listing_stats(username):
    """Get statistics about user's seller listings"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        c.execute("""
            SELECT 
                COUNT(*) as total_listings,
                SUM(CASE WHEN status = 'draft' THEN 1 ELSE 0 END) as draft_count,
                SUM(CASE WHEN status = 'posted' THEN 1 ELSE 0 END) as posted_count,
                SUM(CASE WHEN status = 'sold' THEN 1 ELSE 0 END) as sold_count,
                SUM(CASE WHEN status = 'sold' THEN COALESCE(actual_sale_price, price) ELSE 0 END) as gross_revenue,
                SUM(CASE WHEN status = 'sold' AND original_cost IS NOT NULL THEN COALESCE(actual_sale_price, price) - original_cost ELSE 0 END) as true_profit,
                SUM(CASE WHEN status = 'sold' AND original_cost IS NOT NULL THEN original_cost ELSE 0 END) as total_costs,
                SUM(CASE WHEN status = 'sold' THEN price ELSE 0 END) as original_value,
                AVG(price) as avg_listing_price,
                AVG(CASE WHEN status = 'sold' THEN COALESCE(actual_sale_price, price) END) as avg_sale_price
            FROM seller_listings
            WHERE username = ?
        """, (username,))
        
        row = c.fetchone()
        
        # Validate row structure before accessing indices
        if not row or len(row) < 10:
            logger.error(f"Invalid seller listing stats row structure: {row}")
            return {
                'total_listings': 0,
                'draft_count': 0,
                'posted_count': 0,
                'sold_count': 0,
                'gross_revenue': 0,
                'true_profit': 0,
                'total_costs': 0,
                'net_revenue': 0,
                'avg_listing_price': 0,
                'avg_sale_price': 0,
                'marketplace_breakdown': {}
            }
        
        gross_revenue = row[4] if row[4] is not None else 0
        true_profit = row[5] if row[5] is not None else 0  # Actual profit: (sale price - original cost)
        total_costs = row[6] if row[6] is not None else 0
        original_value = row[7] if row[7] is not None else 0
        net_revenue = gross_revenue - original_value  # Price adjustments: (sale price - listing price)
        
        # Get marketplace breakdown for sold items
        c.execute("""
            SELECT 
                sold_on_marketplace,
                COUNT(*) as count,
                SUM(COALESCE(actual_sale_price, price)) as revenue
            FROM seller_listings
            WHERE username = ? AND status = 'sold' AND sold_on_marketplace IS NOT NULL
            GROUP BY sold_on_marketplace
        """, (username,))
        
        marketplace_data = {}
        for mp_row in c.fetchall():
            marketplace = mp_row[0]
            marketplace_data[marketplace] = {
                'count': mp_row[1],
                'revenue': mp_row[2] or 0
            }
        
        return {
            'total_listings': row[0] or 0,
            'draft_count': row[1] or 0,
            'posted_count': row[2] or 0,
            'sold_count': row[3] or 0,
            'gross_revenue': gross_revenue,  # Total money received
            'true_profit': true_profit,  # Actual profit after costs
            'total_costs': total_costs,  # Total original costs
            'net_revenue': net_revenue,  # Price adjustment profit/loss
            'avg_listing_price': row[8] or 0,
            'avg_sale_price': row[9] or 0,
            'marketplace_breakdown': marketplace_data
        }
# ======================
# SUBSCRIPTION MANAGEMENT
# ======================

@log_errors()
def get_user_subscription(username):
    """Get user's subscription information"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT tier, status, stripe_customer_id, stripe_subscription_id, 
                   current_period_start, current_period_end, cancel_at_period_end,
                   created_at, updated_at
            FROM subscriptions
            WHERE username = ?
        """, (username,))
        
        row = c.fetchone()
        if row:
            return {
                'tier': row[0],
                'status': row[1],
                'stripe_customer_id': row[2],
                'stripe_subscription_id': row[3],
                'current_period_start': row[4],
                'current_period_end': row[5],
                'cancel_at_period_end': row[6],
                'created_at': row[7],
                'updated_at': row[8]
            }
        
        # Return default free tier if no subscription found
        return {
            'tier': 'free',
            'status': 'active',
            'stripe_customer_id': None,
            'stripe_subscription_id': None,
            'current_period_start': None,
            'current_period_end': None,
            'cancel_at_period_end': False,
            'created_at': None,
            'updated_at': None
        }


@log_errors()
def create_or_update_subscription(username, tier, status='active', stripe_customer_id=None, 
                                   stripe_subscription_id=None, current_period_start=None,
                                   current_period_end=None, cancel_at_period_end=False):
    """Create or update user's subscription"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Check if subscription exists
        c.execute("SELECT id FROM subscriptions WHERE username = ?", (username,))
        existing = c.fetchone()
        
        if existing:
            # Update existing subscription
            c.execute("""
                UPDATE subscriptions 
                SET tier = ?, status = ?, stripe_customer_id = ?, stripe_subscription_id = ?,
                    current_period_start = ?, current_period_end = ?, cancel_at_period_end = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE username = ?
            """, (tier, status, stripe_customer_id, stripe_subscription_id,
                  current_period_start, current_period_end, cancel_at_period_end, username))
        else:
            # Create new subscription
            c.execute("""
                INSERT INTO subscriptions (username, tier, status, stripe_customer_id, 
                                          stripe_subscription_id, current_period_start, 
                                          current_period_end, cancel_at_period_end)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (username, tier, status, stripe_customer_id, stripe_subscription_id,
                  current_period_start, current_period_end, cancel_at_period_end))
        
        # Also update the users table for quick access
        c.execute("UPDATE users SET subscription_tier = ? WHERE username = ?", (tier, username))
        
        conn.commit()
        return True


@log_errors()
def log_security_event(ip, path, user_agent, reason, timestamp=None):
    """Log security events for monitoring and analysis with enhanced error handling"""
    if timestamp is None:
        timestamp = datetime.now()
    
    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO security_events (ip_address, path, user_agent, reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (ip, path, user_agent, reason, timestamp))
            conn.commit()
            return True
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e).lower():
            logger.warning(f"Database locked while logging security event for IP {ip}")
            raise  # Re-raise to trigger retry mechanism
        else:
            logger.error(f"Database error logging security event: {e}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error logging security event: {e}")
        raise


@log_errors()
def get_security_events(limit=100, hours=24):
    """Get recent security events"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        cutoff_time = datetime.now() - timedelta(hours=hours)
        c.execute("""
            SELECT ip_address, path, user_agent, reason, timestamp
            FROM security_events
            WHERE timestamp > ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (cutoff_time, limit))
        
        rows = c.fetchall()
        return [{
            'ip_address': row[0],
            'path': row[1],
            'user_agent': row[2],
            'reason': row[3],
            'timestamp': datetime.fromisoformat(row[4]) if isinstance(row[4], str) else row[4]
        } for row in rows]


@log_errors()
def log_subscription_event(username, tier, action, stripe_event_id=None, details=None):
    """Log subscription-related events"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO subscription_history (username, tier, action, stripe_event_id, details)
            VALUES (?, ?, ?, ?, ?)
        """, (username, tier, action, stripe_event_id, details))
        conn.commit()
        return True


@log_errors()
def get_subscription_history(username, limit=50):
    """Get subscription history for a user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT tier, action, stripe_event_id, details, created_at
            FROM subscription_history
            WHERE username = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (username, limit))
        
        rows = c.fetchall()
        return [{
            'tier': row[0],
            'action': row[1],
            'stripe_event_id': row[2],
            'details': row[3],
            'created_at': row[4]
        } for row in rows]


@log_errors()
def cancel_subscription(username):
    """Cancel a user's subscription (sets to free tier)"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE subscriptions 
            SET tier = 'free', status = 'cancelled', cancel_at_period_end = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE username = ?
        """, (username,))
        
        # Update users table
        c.execute("UPDATE users SET subscription_tier = 'free' WHERE username = ?", (username,))
        
        conn.commit()
        return True


@log_errors()
def get_all_subscriptions(tier=None, status=None):
    """Get all subscriptions with optional filtering"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        query = "SELECT username, tier, status, stripe_customer_id, current_period_end, created_at FROM subscriptions WHERE 1=1"
        params = []
        
        if tier:
            query += " AND tier = ?"
            params.append(tier)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        c.execute(query, params)
        rows = c.fetchall()
        
        return [{
            'username': row[0],
            'tier': row[1],
            'status': row[2],
            'stripe_customer_id': row[3],
            'current_period_end': row[4],
            'created_at': row[5]
        } for row in rows]


@log_errors()
def get_subscription_by_customer_id(stripe_customer_id):
    """Get subscription by Stripe customer ID"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT username, tier, status, stripe_subscription_id, 
                   current_period_start, current_period_end
            FROM subscriptions
            WHERE stripe_customer_id = ?
        """, (stripe_customer_id,))
        
        row = c.fetchone()
        if row:
            return {
                'username': row[0],
                'tier': row[1],
                'status': row[2],
                'stripe_subscription_id': row[3],
                'current_period_start': row[4],
                'current_period_end': row[5]
            }
        return None


@log_errors()
def get_subscription_stats():
    """Get subscription statistics for admin dashboard"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        c.execute("""
            SELECT 
                COUNT(*) as total_subscriptions,
                SUM(CASE WHEN tier = 'free' THEN 1 ELSE 0 END) as free_count,
                SUM(CASE WHEN tier = 'standard' THEN 1 ELSE 0 END) as standard_count,
                SUM(CASE WHEN tier = 'pro' THEN 1 ELSE 0 END) as pro_count,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_count,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled_count
            FROM subscriptions
        """)
        
        row = c.fetchone()
        return {
            'total_subscriptions': row[0] or 0,
            'free_count': row[1] or 0,
            'standard_count': row[2] or 0,
            'pro_count': row[3] or 0,
            'active_count': row[4] or 0,
            'cancelled_count': row[5] or 0
        }


# ======================
# CLEANUP
# ======================
# EMAIL VERIFICATION & PASSWORD RESET
# ======================
@log_errors()
def create_verification_token(username, token, expiration_hours=24, code_hash: Optional[str] = None):
    """Create an email verification token and optional numeric code hash."""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        expires_at = datetime.now() + timedelta(hours=expiration_hours)
        try:
            c.execute("""
                INSERT INTO email_verification_tokens (username, token, expires_at, code_hash)
                VALUES (?, ?, ?, ?)
            """, (username, token, expires_at, code_hash))
        except sqlite3.OperationalError as e:
            # Fallback for databases without the code_hash column (should be rare post-migration)
            if "code_hash" in str(e).lower():
                c.execute("""
                    INSERT INTO email_verification_tokens (username, token, expires_at)
                    VALUES (?, ?, ?)
                """, (username, token, expires_at))
            else:
                raise
        conn.commit()
        return True


@log_errors()
def verify_email_token(token):
    """Verify an email token and mark user as verified"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        # Check if token exists and is valid
        c.execute("""
            SELECT username, expires_at, used
            FROM email_verification_tokens
            WHERE token = ?
        """, (token,))
        
        result = c.fetchone()
        if not result:
            return False, "Invalid verification token"
        
        username, expires_at, used = result
        
        if used:
            return False, "Token already used"
        
        # Check expiration
        expires_at = datetime.fromisoformat(expires_at)
        if datetime.now() > expires_at:
            return False, "Token has expired"
        
        # Mark token as used
        c.execute("""
            UPDATE email_verification_tokens
            SET used = 1
            WHERE token = ?
        """, (token,))
        
        # Mark user as verified
        c.execute("""
            UPDATE users
            SET verified = 1
            WHERE username = ?
        """, (username,))
        
        conn.commit()
        logger.info(f"Email verified for user: {username}")
        return True, username


@log_errors()
def get_latest_verification_entry(username: str) -> Optional[Dict[str, Any]]:
    """Return the most recent email verification token entry for a user."""
    if not username:
        return None

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, token, code_hash, expires_at, used, created_at
            FROM email_verification_tokens
            WHERE username = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (username,))
        row = c.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "token": row[1],
            "code_hash": row[2],
            "expires_at": row[3],
            "used": bool(row[4]),
            "created_at": row[5],
        }


@log_errors()
def verify_email_code(username: str, code: str) -> Tuple[bool, str]:
    """Validate a numeric verification code for a user."""
    if not username or not code:
        return False, "Please provide both username and verification code."

    normalized_code = code.strip()
    if not normalized_code.isdigit():
        return False, "Verification code must contain digits only."

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, code_hash, expires_at, used
            FROM email_verification_tokens
            WHERE username = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (username,))
        row = c.fetchone()

        if not row:
            return False, "No verification code found for that account."

        token_id, stored_hash, expires_at_raw, used = row

        if used:
            return False, "This verification code was already used. Request a new one."

        if not stored_hash:
            return False, "A verification code is not available. Use the email link or request a new code."

        if isinstance(expires_at_raw, str):
            try:
                expires_at = datetime.fromisoformat(expires_at_raw)
            except ValueError:
                expires_at = datetime.now() - timedelta(seconds=1)
        else:
            expires_at = expires_at_raw

        if datetime.now() > expires_at:
            return False, "Verification code has expired. Request a new one."

        supplied_hash = hash_verification_code(username, normalized_code)
        if supplied_hash != stored_hash:
            return False, "Incorrect verification code. Double-check the digits and try again."

        c.execute("""
            UPDATE email_verification_tokens
            SET used = 1
            WHERE id = ?
        """, (token_id,))

        c.execute("""
            UPDATE users
            SET verified = 1
            WHERE username = ?
        """, (username,))

        conn.commit()
        logger.info(f"Email verified via code for user: {username}")
        return True, username


@log_errors()
def create_password_reset_token(username, token, expiration_hours=1):
    """Create a password reset token"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        expires_at = datetime.now() + timedelta(hours=expiration_hours)
        c.execute("""
            INSERT INTO password_reset_tokens (username, token, expires_at)
            VALUES (?, ?, ?)
        """, (username, token, expires_at))
        conn.commit()
        return True


@log_errors()
def verify_password_reset_token(token):
    """Verify a password reset token"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        
        c.execute("""
            SELECT username, expires_at, used
            FROM password_reset_tokens
            WHERE token = ?
        """, (token,))
        
        result = c.fetchone()
        if not result:
            return False, None
        
        username, expires_at, used = result
        
        if used:
            return False, None
        
        expires_at = datetime.fromisoformat(expires_at)
        if datetime.now() > expires_at:
            return False, None
        
        return True, username


@log_errors()
def use_password_reset_token(token):
    """Mark a password reset token as used"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE password_reset_tokens
            SET used = 1
            WHERE token = ?
        """, (token,))
        conn.commit()
        return True


@log_errors()
def reset_user_password(username, new_password_hash):
    """Reset a user's password"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE users
            SET password = ?
            WHERE username = ?
        """, (new_password_hash, username))
        conn.commit()
        logger.info(f"Password reset for user: {username}")
        return True


# ======================
# FAVORITES / BOOKMARKS
# ======================

@log_errors()
def add_favorite(username, listing_id, notes=None):
    """Add a listing to user's favorites"""
    if isinstance(listing_id, dict):
        listing_id = listing_id.get("id")
    if listing_id is None:
        return False

    try:
        with get_pool().get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO favorites (username, listing_id, notes)
                VALUES (?, ?, ?)
            """, (username, listing_id, notes))
            conn.commit()
            logger.info(f"Added favorite for {username}: listing {listing_id}")
            return True
    except sqlite3.IntegrityError:
        # Already favorited
        return False


@log_errors()
def remove_favorite(username, listing_id):
    """Remove a listing from user's favorites"""
    if isinstance(listing_id, dict):
        listing_id = listing_id.get("id")
    if listing_id is None:
        return False

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM favorites
            WHERE username = ? AND listing_id = ?
        """, (username, listing_id))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def get_favorites(username, limit=100):
    """Get user's favorite listings"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT l.id, l.title, l.price, l.link, l.image_url, l.source, l.created_at,
                   f.notes, f.created_at as favorited_at
            FROM favorites f
            JOIN listings l ON f.listing_id = l.id
            WHERE f.username = ?
            ORDER BY f.created_at DESC
            LIMIT ?
        """, (username, limit))
        
        rows = c.fetchall()
        return [{
            'id': row[0],
            'title': row[1],
            'price': row[2],
            'link': row[3],
            'image_url': row[4],
            'source': row[5],
            'created_at': row[6],
            'notes': row[7],
            'favorited_at': row[8]
        } for row in rows]


@log_errors()
def is_favorited(username, listing_id):
    """Check if a listing is favorited by user"""
    if isinstance(listing_id, dict):
        listing_id = listing_id.get("id")
    if listing_id is None:
        return False

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 1 FROM favorites
            WHERE username = ? AND listing_id = ?
        """, (username, listing_id))
        return c.fetchone() is not None


@log_errors()
def update_favorite_notes(username, listing_id, notes):
    """Update notes for a favorite"""
    if isinstance(listing_id, dict):
        listing_id = listing_id.get("id")
    if listing_id is None:
        return False

    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE favorites
            SET notes = ?
            WHERE username = ? AND listing_id = ?
        """, (notes, username, listing_id))
        conn.commit()
        return c.rowcount > 0


# ======================
# ADMIN SEARCH INSIGHTS
# ======================


@log_errors()
def get_search_preferences(limit=50):
    """Aggregate recent search settings for admin insights."""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 
                s.username,
                MAX(CASE WHEN s.key = 'keywords' THEN s.value END) AS keywords,
                MAX(CASE WHEN s.key = 'location' THEN s.value END) AS location,
                MAX(CASE WHEN s.key = 'radius' THEN s.value END) AS radius,
                MAX(CASE WHEN s.key = 'min_price' THEN s.value END) AS min_price,
                MAX(CASE WHEN s.key = 'max_price' THEN s.value END) AS max_price,
                MAX(s.updated_at) AS updated_at
            FROM settings s
            JOIN users u ON u.username = s.username
            WHERE s.username IS NOT NULL
            GROUP BY s.username
            ORDER BY MAX(s.updated_at) DESC
            LIMIT ?
        """, (limit,))
        rows = c.fetchall()

    insights = []
    for row in rows:
        insights.append({
            'username': row[0],
            'keywords': row[1] or '',
            'location': row[2] or '',
            'radius': row[3] or '',
            'min_price': row[4],
            'max_price': row[5],
            'updated_at': _to_datetime_string(row[6]),
        })
    return insights


@log_errors()
def get_recent_saved_searches(limit=50):
    """Return the most recent saved searches for all users."""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT 
                username,
                name,
                keywords,
                location,
                min_price,
                max_price,
                radius,
                created_at
            FROM saved_searches
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = c.fetchall()

    searches = []
    for row in rows:
        searches.append({
            'username': row[0],
            'name': row[1],
            'keywords': row[2] or '',
            'location': row[3] or '',
            'min_price': row[4],
            'max_price': row[5],
            'radius': row[6],
            'created_at': _to_datetime_string(row[7]),
        })
    return searches


# ======================
# SAVED SEARCHES
# ======================

@log_errors()
def create_saved_search(username, name, keywords=None, min_price=None, max_price=None, 
                       sources=None, location=None, radius=None, notify_new=True):
    """Create a saved search"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO saved_searches 
            (username, name, keywords, min_price, max_price, sources, location, radius, notify_new)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, name, keywords, min_price, max_price, sources, location, radius, notify_new))
        conn.commit()
        return c.lastrowid
def get_saved_searches(username):
    """Get all saved searches for a user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, name, keywords, min_price, max_price, sources, location, radius,
                   notify_new, created_at, last_run
            FROM saved_searches
            WHERE username = ?
            ORDER BY created_at DESC
        """, (username,))
        
        rows = c.fetchall()
        return [{
            'id': row[0],
            'name': row[1],
            'keywords': row[2],
            'min_price': row[3],
            'max_price': row[4],
            'sources': row[5],
            'location': row[6],
            'radius': row[7],
            'notify_new': row[8],
            'created_at': row[9],
            'last_run': row[10]
        } for row in rows]


@log_errors()
def get_saved_search_by_id(search_id: int, username: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Fetch a saved search by ID, optionally enforcing ownership."""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        if username:
            c.execute("""
                SELECT id, username, name, keywords, min_price, max_price, sources, location, radius,
                       notify_new, created_at, last_run
                FROM saved_searches
                WHERE id = ? AND username = ?
            """, (search_id, username))
        else:
            c.execute("""
                SELECT id, username, name, keywords, min_price, max_price, sources, location, radius,
                       notify_new, created_at, last_run
                FROM saved_searches
                WHERE id = ?
            """, (search_id,))
        row = c.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "username": row[1],
        "name": row[2],
        "keywords": row[3],
        "min_price": row[4],
        "max_price": row[5],
        "sources": row[6],
        "location": row[7],
        "radius": row[8],
        "notify_new": row[9],
        "created_at": _to_datetime_string(row[10]),
        "last_run": _to_datetime_string(row[11]),
    }


@log_errors()
def delete_saved_search(search_id, username):
    """Delete a saved search"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM saved_searches
            WHERE id = ? AND username = ?
        """, (search_id, username))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def update_saved_search_last_run(search_id):
    """Update the last run timestamp for a saved search"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE saved_searches
            SET last_run = ?
            WHERE id = ?
        """, (datetime.now(), search_id))
        conn.commit()


# ======================
# PRICE ALERTS
# ======================

@log_errors()
def create_price_alert(username, keywords, threshold_price, alert_type='under'):
    """Create a price alert"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO price_alerts (username, keywords, threshold_price, alert_type)
            VALUES (?, ?, ?, ?)
        """, (username, keywords, threshold_price, alert_type))
        conn.commit()
        return c.lastrowid


@log_errors()
def get_price_alerts(username):
    """Get all price alerts for a user"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, keywords, threshold_price, alert_type, active, last_triggered, created_at
            FROM price_alerts
            WHERE username = ?
            ORDER BY created_at DESC
        """, (username,))
        
        rows = c.fetchall()
        return [{
            'id': row[0],
            'keywords': row[1],
            'threshold_price': row[2],
            'alert_type': row[3],
            'active': row[4],
            'last_triggered': row[5],
            'created_at': row[6]
        } for row in rows]


@log_errors()
def delete_price_alert(alert_id, username):
    """Delete a price alert"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            DELETE FROM price_alerts
            WHERE id = ? AND username = ?
        """, (alert_id, username))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def toggle_price_alert(alert_id, username):
    """Toggle a price alert active status"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE price_alerts
            SET active = NOT active
            WHERE id = ? AND username = ?
        """, (alert_id, username))
        conn.commit()
        return c.rowcount > 0


@log_errors()
def update_price_alert_triggered(alert_id):
    """Update the last triggered timestamp"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE price_alerts
            SET last_triggered = ?
            WHERE id = ?
        """, (datetime.now(), alert_id))
        conn.commit()


@log_errors()
def get_active_price_alerts():
    """Get all active price alerts"""
    with get_pool().get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT id, username, keywords, threshold_price, alert_type, last_triggered
            FROM price_alerts
            WHERE active = 1
        """)
        
        rows = c.fetchall()
        return [{
            'id': row[0],
            'username': row[1],
            'keywords': row[2],
            'threshold_price': row[3],
            'alert_type': row[4],
            'last_triggered': row[5]
        } for row in rows]


# ======================
def close_database():
    """Close all database connections"""
    global _connection_pool
    if _connection_pool:
        _connection_pool.close_all()
        _connection_pool = None
    
    # Stop the activity logger
    stop_activity_logger()


# Start the activity logger when module is imported
start_activity_logger()