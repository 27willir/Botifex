"""
WebSocket Manager for Real-Time Notifications
Handles real-time updates for listings, alerts, and system status
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple, Callable, TypeVar

from flask import current_app, request
from flask_login import current_user
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
from utils import logger
import db_enhanced
from observability import log_event, log_alert

try:  # Optional dependency; realtime features gracefully degrade without Redis
    import redis  # type: ignore
except ImportError:  # pragma: no cover - fallback when redis is unavailable
    redis = None  # type: ignore

try:  # JWT is used for secure websocket handshakes
    import jwt
    from jwt import InvalidTokenError
except ImportError:  # pragma: no cover - if PyJWT missing, tokens cannot be verified
    jwt = None  # type: ignore
    InvalidTokenError = Exception  # type: ignore

# Initialize SocketIO (configured in app.py)
socketio: Optional[SocketIO] = None

# Redis / realtime configuration
redis_client: Optional["redis.Redis"] = None
redis_enabled = False
_redis_listener: Optional[threading.Thread] = None
_redis_stop_event = threading.Event()
REALTIME_EVENT_CHANNEL = "realtime:events"
PRESENCE_TTL_SECONDS = 60
CHANNEL_TYPING_TTL_SECONDS = 6

# JWT configuration for websocket tokens
jwt_secret: Optional[str] = None
jwt_audience: Optional[str] = None
jwt_issuer: Optional[str] = None
JWT_LEEWAY_SECONDS = 10

# Connection bookkeeping
_connection_lock = Lock()
_connection_users: Dict[str, Dict[str, Any]] = {}

# Typing state cache (fallback when Redis unavailable)
DM_TYPING_TTL_SECONDS = 6
_typing_lock = Lock()
_typing_states: Dict[Tuple[int, str], float] = {}

# Slow-mode fallback cache
_slow_mode_lock = Lock()
_slow_mode_cache: Dict[Tuple[int, str], float] = {}

# Channel presence and typing fallback caches
_channel_presence_lock = Lock()
_channel_presence_cache: Dict[int, Dict[str, float]] = {}
_channel_typing_lock = Lock()
_channel_typing_cache: Dict[int, Dict[str, float]] = {}

# Redis circuit breaker configuration
_redis_circuit_lock = Lock()
_redis_circuit_failures = 0
_redis_circuit_open_until: Optional[float] = None
_redis_failure_threshold = int(os.getenv("REALTIME_REDIS_FAILURE_THRESHOLD", "5"))
_redis_cooldown_seconds = int(os.getenv("REALTIME_REDIS_COOLDOWN_SECONDS", "60"))

T = TypeVar("T")


def _redis_circuit_allows() -> bool:
    if not redis_enabled or not redis_client:
        return False
    with _redis_circuit_lock:
        if _redis_circuit_open_until:
            now = time.time()
            if now < _redis_circuit_open_until:
                return False
            _redis_circuit_open_until = None
            log_event("realtime.redis.circuit_closed", severity="info")
        return True


def _record_redis_success() -> None:
    with _redis_circuit_lock:
        if _redis_circuit_failures:
            _redis_circuit_failures = 0


def _record_redis_failure(operation: str, exc: Exception) -> None:
    message = str(exc)
    with _redis_circuit_lock:
        _redis_circuit_failures += 1
        failures = _redis_circuit_failures
        threshold = max(1, _redis_failure_threshold)
        if failures >= threshold:
            cooldown = max(5, _redis_cooldown_seconds)
            _redis_circuit_open_until = time.time() + cooldown
            _redis_circuit_failures = 0
            log_alert(
                "realtime.redis.circuit_open",
                f"Redis circuit opened after repeated failures ({operation})",
                severity="error",
                operation=operation,
                cooldown_seconds=cooldown,
                error=message,
            )
        else:
            log_alert(
                "realtime.redis.failure",
                f"Redis operation failed ({operation})",
                severity="warning",
                operation=operation,
                failures=failures,
                error=message,
            )


def _with_redis(operation: str, handler: Callable[["redis.Redis"], T], *, default: Any = None) -> Any:
    if not _redis_circuit_allows():
        return default
    assert redis_client is not None  # for type-checkers
    try:
        result = handler(redis_client)
        _record_redis_success()
        return result
    except Exception as exc:  # pragma: no cover - depends on runtime conditions
        _record_redis_failure(operation, exc)
        return default


def get_realtime_health() -> Dict[str, Any]:
    """Expose realtime subsystem status for health/readiness checks."""
    circuit_open = False
    cooldown_remaining = 0.0
    failures = 0
    with _redis_circuit_lock:
        failures = _redis_circuit_failures
        if _redis_circuit_open_until:
            now = time.time()
            if now < _redis_circuit_open_until:
                circuit_open = True
                cooldown_remaining = max(0.0, _redis_circuit_open_until - now)
            else:
                _redis_circuit_open_until = None

    redis_status = "enabled" if redis_enabled and redis_client else "disabled"
    listener_alive = _redis_listener.is_alive() if _redis_listener else False

    return {
        "status": "ok" if redis_status == "enabled" and not circuit_open else "degraded" if redis_status == "enabled" else "disabled",
        "redis": {
            "enabled": redis_enabled,
            "client": bool(redis_client),
            "listener_alive": listener_alive,
        },
        "circuit": {
            "open": circuit_open,
            "failure_count": failures,
            "cooldown_remaining": round(cooldown_remaining, 3),
        },
        "connected_clients": get_connected_users(),
    }


class SlowModeViolation(RuntimeError):
    """Raised when a user hits channel slow-mode limits."""

    def __init__(self, retry_after: float) -> None:
        super().__init__("Slow mode is active")
        self.retry_after = retry_after


def init_socketio(app) -> SocketIO:
    """Initialize SocketIO with the Flask app and configure realtime backends."""
    global socketio, jwt_secret, jwt_audience, jwt_issuer

    socketio_instance = SocketIO(
        app,
        cors_allowed_origins="*",
        logger=False,
        engineio_logger=False,
        async_mode="threading",
    )

    socketio = socketio_instance
    jwt_secret = app.config.get("REALTIME_JWT_SECRET")
    jwt_audience = app.config.get("REALTIME_JWT_AUDIENCE")
    jwt_issuer = app.config.get("REALTIME_JWT_ISSUER")

    _init_redis(app.config.get("REALTIME_REDIS_URL") or os.getenv("REDIS_URL"))
    register_events()
    
    logger.info("[OK] WebSocket server initialized")
    return socketio_instance


def _init_redis(redis_url: Optional[str]) -> None:
    global redis_client, redis_enabled, _redis_listener

    if not redis_url or redis is None:
        logger.info("Realtime Redis integration disabled (no REDIS_URL or redis library).")
        redis_client = None
        redis_enabled = False
        return

    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True)
        client.ping()
    except Exception as exc:  # pragma: no cover - depends on deployment
        logger.warning(f"Realtime Redis connection failed: {exc}")
        redis_client = None
        redis_enabled = False
        return

    redis_client = client
    redis_enabled = True
    logger.info("Realtime Redis integration enabled.")

    if _redis_listener is None or not _redis_listener.is_alive():
        _redis_stop_event.clear()
        _redis_listener = threading.Thread(target=_listen_for_events, name="RealtimeEventBus", daemon=True)
        _redis_listener.start()


def _listen_for_events() -> None:
    if not redis_enabled or not redis_client:
        return

    pubsub = redis_client.pubsub()
    pubsub.subscribe(REALTIME_EVENT_CHANNEL)
    logger.info("Realtime event listener started.")

    try:
        for message in pubsub.listen():  # pragma: no branch - loop exits via stop event
            if _redis_stop_event.is_set():
                break
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if not data:
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("Discarded malformed realtime event: %s", data)
                continue
            _handle_bus_event(event)
    except Exception as exc:  # pragma: no cover - depends on runtime conditions
        logger.warning(f"Realtime event listener stopped unexpectedly: {exc}")
    finally:
        pubsub.close()
        logger.info("Realtime event listener stopped.")


def register_events() -> None:
    """Register WebSocket event handlers."""

    @socketio.on("connect")  # type: ignore[arg-type]
    def handle_connect():
        try:
            username, claims = _authenticate_connection()
        except ConnectionRefusedError as exc:
            logger.warning(f"WebSocket connection rejected: {exc}")
            raise

        _store_connection_user(request.sid, username, claims)
        join_room(f"user_{username}")
        _set_presence(username, online=True)

        emit(
            "connection_status",
            {
                "status": "connected",
                "username": username,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            },
        )
        logger.info("WebSocket: %s connected", username)

    @socketio.on("disconnect")  # type: ignore[arg-type]
    def handle_disconnect():
        record = _release_connection_user(request.sid)
        if not record:
            return
        username = record.get("username")
        if not username:
            return

        channels_joined = record.get("channels") or set()
        for channel_id in list(channels_joined):
            try:
                channel_id_int = int(channel_id)
            except (TypeError, ValueError):
                continue
            leave_room(f"channel_{channel_id_int}")
            _update_channel_presence(channel_id_int, username, online=False)

        leave_room(f"user_{username}")
        _set_presence(username, online=False)

        cleared_conversations = set(_clear_typing_state(username))
        dm_rooms: List[int] = []
        for room_name in rooms():
            if isinstance(room_name, str) and room_name.startswith("dm_"):
                try:
                    dm_rooms.append(int(room_name.split("_", 1)[1]))
                except (ValueError, IndexError):
                    continue

        timestamp = datetime.utcnow()
        for conv_id in dm_rooms:
            if conv_id in cleared_conversations:
                broadcast_dm_typing(conv_id, username, timestamp, is_typing=False)
            _emit_dm_presence(conv_id)
    
        logger.info("WebSocket: %s disconnected", username)

    @socketio.on("subscribe_scraper_status")  # type: ignore[arg-type]
    def handle_subscribe_scraper_status():
        username = _get_ws_username()
        if not username:
            return
        join_room("scraper_status")
        logger.debug("WebSocket: %s subscribed to scraper status", username)
        emit("subscribed", {"channel": "scraper_status"})

    @socketio.on("unsubscribe_scraper_status")  # type: ignore[arg-type]
    def handle_unsubscribe_scraper_status():
        username = _get_ws_username()
        if not username:
            return
        leave_room("scraper_status")
        logger.debug("WebSocket: %s unsubscribed from scraper status", username)
        emit("unsubscribed", {"channel": "scraper_status"})

    @socketio.on("ping")  # type: ignore[arg-type]
    def handle_ping():
        emit("pong", {"timestamp": datetime.utcnow().isoformat() + "Z"})

    @socketio.on("dm.join")  # type: ignore[arg-type]
    def handle_dm_join(data: Optional[Dict[str, Any]]):
        username = _get_ws_username()
        if not username:
            return
        payload = data or {}
        conversation_id = payload.get("conversation_id")
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return

        if not db_enhanced.is_user_in_dm_conversation(username, conversation_id):
            return

        join_room(f"dm_{conversation_id}")
        try:
            db_enhanced.mark_dm_participant_active(conversation_id, username)
        except Exception as exc:  # pragma: no cover - protects from DB errors
            logger.warning(f"Failed to mark DM participant active during join: {exc}")

        emit("dm.joined", {"conversation_id": conversation_id, "sid": request.sid})
        _emit_dm_presence(conversation_id)

    @socketio.on("dm.leave")  # type: ignore[arg-type]
    def handle_dm_leave(data: Optional[Dict[str, Any]]):
        username = _get_ws_username()
        if not username:
            return
        payload = data or {}
        conversation_id = payload.get("conversation_id")
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return

        if not db_enhanced.is_user_in_dm_conversation(username, conversation_id):
            return

        leave_room(f"dm_{conversation_id}")
        broadcast_dm_typing(conversation_id, username, datetime.utcnow(), is_typing=False)
        _clear_typing_state_for_conversation(conversation_id, username)
        _emit_dm_presence(conversation_id)

    @socketio.on("dm.typing")  # type: ignore[arg-type]
    def handle_dm_typing(data: Optional[Dict[str, Any]]):
        username = _get_ws_username()
        if not username:
            return
        payload = data or {}
        conversation_id = payload.get("conversation_id")
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return

        if not db_enhanced.is_user_in_dm_conversation(username, conversation_id):
            return

        expires_at = _register_typing_state(conversation_id, username)
        try:
            db_enhanced.mark_dm_participant_active(conversation_id, username)
        except Exception as exc:
            logger.warning(f"Failed to mark DM participant active during typing: {exc}")
        broadcast_dm_typing(conversation_id, username, expires_at)

    @socketio.on("channel.join")  # type: ignore[arg-type]
    def handle_channel_join(data: Optional[Dict[str, Any]]):
        username = _get_ws_username()
        if not username:
            return
        payload = data or {}
        channel_id = payload.get("channel_id")
        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            return

        channel = db_enhanced.get_server_channel(channel_id)
        if not channel:
            return

        membership = db_enhanced.get_server_membership(channel["server_id"], username, include_permissions=False)
        if not membership or membership.get("status") != "active":
            return

        join_room(f"channel_{channel_id}")
        _add_connection_channel(request.sid, channel_id)
        _update_channel_presence(channel_id, username, online=True)

    @socketio.on("channel.leave")  # type: ignore[arg-type]
    def handle_channel_leave(data: Optional[Dict[str, Any]]):
        username = _get_ws_username()
        if not username:
            return
        payload = data or {}
        channel_id = payload.get("channel_id")
        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            return

        leave_room(f"channel_{channel_id}")
        _remove_connection_channel(request.sid, channel_id)
        _update_channel_presence(channel_id, username, online=False)

    @socketio.on("channel.typing")  # type: ignore[arg-type]
    def handle_channel_typing(data: Optional[Dict[str, Any]]):
        username = _get_ws_username()
        if not username:
            return
        payload = data or {}
        channel_id = payload.get("channel_id")
        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            return

        if not _connection_in_channel(request.sid, channel_id):
            return

        expires_at = _register_channel_typing_state(channel_id, username)
        broadcast_channel_typing(channel_id, username, expires_at)


def _authenticate_connection() -> Tuple[str, Dict[str, Any]]:
    """Validate socket connections using JWT tokens and/or Flask session."""

    username: Optional[str] = None
    claims: Dict[str, Any] = {}

    token = request.args.get("token")
    if token:
        if not jwt or not jwt_secret:
            raise ConnectionRefusedError("token_auth_disabled")
        decode_kwargs: Dict[str, Any] = {
            "algorithms": ["HS256"],
            "leeway": JWT_LEEWAY_SECONDS,
        }
        if jwt_audience:
            decode_kwargs["audience"] = jwt_audience
        if jwt_issuer:
            decode_kwargs["issuer"] = jwt_issuer
        try:
            claims = jwt.decode(token, jwt_secret, **decode_kwargs)
        except InvalidTokenError as exc:
            raise ConnectionRefusedError(f"invalid_token: {exc}")
        username = claims.get("sub")

    if current_user.is_authenticated:
        if username and username != current_user.id:
            raise ConnectionRefusedError("token_mismatch")
        username = current_user.id
        if not claims:
            claims = {"sub": username}

    if not username:
        raise ConnectionRefusedError("authentication_required")

    return username, claims


def _store_connection_user(sid: str, username: str, claims: Dict[str, Any]) -> None:
    with _connection_lock:
        _connection_users[sid] = {"username": username, "claims": claims, "channels": set()}


def _release_connection_user(sid: str) -> Optional[Dict[str, Any]]:
    with _connection_lock:
        return _connection_users.pop(sid, None)


def _get_ws_username() -> Optional[str]:
    with _connection_lock:
        record = _connection_users.get(request.sid)
    return record.get("username") if record else None


def _add_connection_channel(sid: str, channel_id: int) -> None:
    with _connection_lock:
        record = _connection_users.get(sid)
        if record is not None:
            channels = record.setdefault("channels", set())
            channels.add(channel_id)


def _remove_connection_channel(sid: str, channel_id: int) -> None:
    with _connection_lock:
        record = _connection_users.get(sid)
        if record is not None:
            channels = record.setdefault("channels", set())
            channels.discard(channel_id)


def _connection_in_channel(sid: str, channel_id: int) -> bool:
    with _connection_lock:
        record = _connection_users.get(sid)
        if not record:
            return False
        channels = record.get("channels", set())
        return channel_id in channels


def _set_presence(username: str, online: bool) -> None:
    payload = json.dumps({
        "status": "online" if online else "offline",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })

    key = f"realtime:presence:user:{username}"
    if online:
        success = bool(_with_redis(
            "presence.set",
            lambda client: client.setex(key, PRESENCE_TTL_SECONDS, payload),
            default=False,
        ))
    else:
        result = _with_redis(
            "presence.clear",
            lambda client: client.delete(key),
            default=0,
        )
        success = bool(result)

    if not success:
        with _connection_lock:
            record = _connection_users.get(request.sid)
            if record is not None:
                record["presence"] = payload


def _channel_presence_key(channel_id: int) -> str:
    return f"realtime:channel:presence:{channel_id}"


def _channel_typing_key(channel_id: int) -> str:
    return f"realtime:channel:typing:{channel_id}"


def _collect_channel_presence_snapshot(channel_id: int) -> List[Dict[str, Any]]:
    now = time.time()
    participants: List[Dict[str, Any]] = []

    key = _channel_presence_key(channel_id)
    records = _with_redis(
        "channel.presence.hgetall",
        lambda client: client.hgetall(key),
        default={},
    ) or {}

    if records:
        for username, ts in list(records.items()):
            try:
                last_active = float(ts)
            except (TypeError, ValueError):
                last_active = now
            if last_active + PRESENCE_TTL_SECONDS < now:
                _with_redis(
                    "channel.presence.hdel",
                    lambda client, user=username: client.hdel(key, user),
                    default=0,
                )
                continue
            participants.append({
                "username": username,
                "last_active": datetime.utcfromtimestamp(last_active).isoformat() + "Z",
            })

    with _channel_presence_lock:
        entries = _channel_presence_cache.get(channel_id, {})
        for username, ts in list(entries.items()):
            if ts + PRESENCE_TTL_SECONDS < now:
                del entries[username]
                continue
            participants.append({
                "username": username,
                "last_active": datetime.utcfromtimestamp(ts).isoformat() + "Z",
            })
        if not entries:
            _channel_presence_cache.pop(channel_id, None)

    participants.sort(key=lambda item: item["username"])
    return participants


def _emit_channel_presence(channel_id: int, *, participants: Optional[List[Dict[str, Any]]] = None, from_bus: bool = False) -> None:
    snapshot = participants if participants is not None else _collect_channel_presence_snapshot(channel_id)
    payload = {"channel_id": channel_id, "participants": snapshot}
    if not from_bus:
        _publish_event("channel.presence", payload)
    if socketio:
        try:
            socketio.emit("channel.presence", payload, room=f"channel_{channel_id}")
        except Exception as exc:
            logger.warning(f"Failed to broadcast channel presence for {channel_id}: {exc}")


def _update_channel_presence(channel_id: int, username: str, online: bool) -> None:
    now_ts = time.time()
    key = _channel_presence_key(channel_id)
    _with_redis(
        "channel.presence.update",
        lambda client: (
            client.hset(key, username, now_ts),
            client.expire(key, PRESENCE_TTL_SECONDS),
        )
        if online
        else client.hdel(key, username),
        default=None,
    )

    with _channel_presence_lock:
        entries = _channel_presence_cache.setdefault(channel_id, {})
        if online:
            entries[username] = now_ts
        else:
            entries.pop(username, None)
            if not entries:
                _channel_presence_cache.pop(channel_id, None)

    if not online:
        _clear_channel_typing_state(channel_id, username, broadcast=True)

    snapshot = _collect_channel_presence_snapshot(channel_id)
    _emit_channel_presence(channel_id, participants=snapshot)


def _register_channel_typing_state(channel_id: int, username: str) -> datetime:
    expires_at = datetime.utcnow() + timedelta(seconds=CHANNEL_TYPING_TTL_SECONDS)
    expiry_ts = expires_at.timestamp()

    key = _channel_typing_key(channel_id)
    _with_redis(
        "channel.typing.set",
        lambda client: (
            client.hset(key, username, expiry_ts),
            client.expire(key, CHANNEL_TYPING_TTL_SECONDS + 2),
        ),
        default=None,
    )

    with _channel_typing_lock:
        channel_map = _channel_typing_cache.setdefault(channel_id, {})
        channel_map[username] = expiry_ts

    return expires_at


def _clear_channel_typing_state(channel_id: int, username: str, *, broadcast: bool = True) -> None:
    key = _channel_typing_key(channel_id)
    _with_redis(
        "channel.typing.clear",
        lambda client: client.hdel(key, username),
        default=0,
    )

    with _channel_typing_lock:
        channel_map = _channel_typing_cache.get(channel_id)
        if channel_map and username in channel_map:
            del channel_map[username]
            if not channel_map:
                _channel_typing_cache.pop(channel_id, None)

    if broadcast:
        broadcast_channel_typing(channel_id, username, datetime.utcnow(), is_typing=False)



def _publish_event(event_type: str, payload: Dict[str, Any]) -> None:
    message = json.dumps({"event": event_type, "payload": payload})
    _with_redis(
        "event.publish",
        lambda client: client.publish(REALTIME_EVENT_CHANNEL, message),
        default=None,
    )


def _handle_bus_event(event: Dict[str, Any]) -> None:
    event_type = event.get("event")
    payload = event.get("payload") or {}

    if event_type == "dm.message":
        broadcast_dm_message(
            payload.get("conversation_id"),
            payload.get("message"),
            sender=payload.get("sender"),
            from_bus=True,
        )
    elif event_type == "dm.read":
        broadcast_dm_read_receipt(
            payload.get("conversation_id"),
            payload.get("username"),
            payload.get("message_id"),
            from_bus=True,
        )
    elif event_type == "dm.reaction":
        broadcast_dm_reaction(
            payload.get("conversation_id"),
            payload.get("message_id"),
            payload.get("reactions", []),
            from_bus=True,
        )
    elif event_type == "dm.typing":
        expires_at = payload.get("expires_at")
        try:
            expires_at_dt = datetime.fromisoformat(expires_at.replace("Z", "")) if isinstance(expires_at, str) else datetime.utcnow()
        except Exception:  # pragma: no cover - defensive parsing
            expires_at_dt = datetime.utcnow()
        broadcast_dm_typing(
            payload.get("conversation_id"),
            payload.get("username"),
            expires_at_dt,
            is_typing=payload.get("typing", True),
            from_bus=True,
        )
    elif event_type == "listing.new":
        if isinstance(payload, dict):
            broadcast_new_listing(payload, from_bus=True)
    elif event_type == "user.notification":
        username = payload.get("username")
        if username:
            notify_user(
                username,
                payload.get("type", "generic"),
                payload.get("data") or {},
                timestamp=payload.get("timestamp"),
                from_bus=True,
            )
    elif event_type == "scraper.status":
        if isinstance(payload, dict):
            broadcast_scraper_status(payload, from_bus=True)
    elif event_type == "system.message":
        broadcast_system_message(
            payload.get("message", ""),
            payload.get("level", "info"),
            from_bus=True,
            timestamp=payload.get("timestamp"),
        )
    elif event_type == "channel.presence":
        channel_id = payload.get("channel_id")
        if channel_id is None:
            return
        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            return
        participants = payload.get("participants") or []
        _emit_channel_presence(channel_id, participants=participants, from_bus=True)
    elif event_type == "channel.typing":
        channel_id = payload.get("channel_id")
        username = payload.get("username")
        if channel_id is None or not username:
            return
        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            return
        expires_at = payload.get("expires_at")
        try:
            expires_at_dt = datetime.fromisoformat(expires_at.replace("Z", "")) if isinstance(expires_at, str) else datetime.utcnow()
        except Exception:
            expires_at_dt = datetime.utcnow()
        if not payload.get("typing", True):
            _clear_channel_typing_state(channel_id, username, broadcast=False)
        broadcast_channel_typing(
            channel_id,
            username,
            expires_at_dt,
            is_typing=payload.get("typing", True),
            from_bus=True,
        )


def _cleanup_typing_states(now_timestamp: Optional[float] = None) -> None:
    current = now_timestamp if now_timestamp is not None else time.time()
    with _typing_lock:
        stale_keys = [key for key, expiry in _typing_states.items() if expiry <= current]
        for key in stale_keys:
            del _typing_states[key]


def _register_typing_state(conversation_id: int, username: str) -> datetime:
    expires_at = datetime.utcnow() + timedelta(seconds=DM_TYPING_TTL_SECONDS)
    expiry_ts = expires_at.timestamp()

    key = f"realtime:dm:typing:{conversation_id}"
    _with_redis(
        "dm.typing.set",
        lambda client: (
            client.hset(key, username, expiry_ts),
            client.expire(key, DM_TYPING_TTL_SECONDS + 2),
        ),
        default=None,
    )

    with _typing_lock:
        _typing_states[(conversation_id, username)] = expiry_ts
    _cleanup_typing_states(expiry_ts)
    return expires_at


def _clear_typing_state(username: str) -> List[int]:
    affected: List[int] = []
    with _typing_lock:
        for (conv_id, user) in list(_typing_states.keys()):
            if user == username:
                affected.append(conv_id)
                del _typing_states[(conv_id, user)]

    for conv_id in affected:
        _with_redis(
            "dm.typing.clear_all",
            lambda client, cid=conv_id: client.hdel(f"realtime:dm:typing:{cid}", username),
            default=0,
        )
    return affected


def _clear_typing_state_for_conversation(conversation_id: int, username: str) -> None:
    with _typing_lock:
        _typing_states.pop((conversation_id, username), None)

    _with_redis(
        "dm.typing.clear",
        lambda client: client.hdel(f"realtime:dm:typing:{conversation_id}", username),
        default=0,
    )


def _emit_dm_presence(conversation_id: int) -> None:
    if not socketio:
        return
    try:
        participants = db_enhanced.list_dm_participants(conversation_id)
    except Exception as exc:
        logger.warning(f"Failed to load DM presence for conversation {conversation_id}: {exc}")
        return

    try:
        socketio.emit(
            "dm.presence",
            {"conversation_id": conversation_id, "participants": participants},
            room=f"dm_{conversation_id}",
        )
    except Exception as exc:
        logger.warning(f"Failed to broadcast DM presence for conversation {conversation_id}: {exc}")


# ======================
# BROADCAST FUNCTIONS
# ======================

def broadcast_new_listing(listing_data: Dict[str, Any], *, from_bus: bool = False) -> None:
    """Broadcast a new listing to all connected clients."""
    if not from_bus:
        _publish_event("listing.new", listing_data)
    if socketio:
        try:
            socketio.emit(
                "new_listing",
                {
                    "id": listing_data.get("id"),
                    "title": listing_data.get("title"),
                    "price": listing_data.get("price"),
                    "link": listing_data.get("link"),
                    "source": listing_data.get("source"),
                    "image_url": listing_data.get("image_url"),
                    "created_at": listing_data.get("created_at"),
                },
                namespace="/",
                room=None,
            )
            logger.debug("Broadcast new listing: %s", listing_data.get("title"))
        except Exception as exc:
            logger.error(f"Error broadcasting new listing: {exc}")


def notify_user(
    username: str,
    notification_type: str,
    data: Dict[str, Any],
    *,
    timestamp: Optional[str] = None,
    from_bus: bool = False,
) -> None:
    """Send a targeted notification to a specific user."""
    timestamp_value = timestamp or datetime.utcnow().isoformat() + "Z"
    if not from_bus:
        _publish_event(
            "user.notification",
            {
                "username": username,
                "type": notification_type,
                "data": data,
                "timestamp": timestamp_value,
            },
        )
    if socketio:
        try:
            socketio.emit(
                "notification",
                {
                    "type": notification_type,
                    "data": data,
                    "timestamp": timestamp_value,
                },
                namespace="/",
                room=f"user_{username}",
            )
            logger.debug("Notified user %s: %s", username, notification_type)
        except Exception as exc:
            logger.error(f"Error notifying user: {exc}")


def broadcast_scraper_status(status_data: Dict[str, Any], *, from_bus: bool = False) -> None:
    """Broadcast scraper status changes."""
    timestamp_value = status_data.get("timestamp") or datetime.utcnow().isoformat() + "Z"
    if not from_bus:
        payload = dict(status_data)
        payload["timestamp"] = timestamp_value
        _publish_event("scraper.status", payload)
    else:
        payload = status_data
    if socketio:
        try:
            socketio.emit(
                "scraper_status_update",
                {
                    "facebook": payload.get("facebook"),
                    "craigslist": payload.get("craigslist"),
                    "ksl": payload.get("ksl"),
                    "timestamp": timestamp_value,
                },
                namespace="/",
                room="scraper_status",
            )
            logger.debug("Broadcast scraper status update")
        except Exception as exc:
            logger.error(f"Error broadcasting scraper status: {exc}")


def notify_price_alert_triggered(username: str, alert_data: Dict[str, Any]) -> None:
    """Notify user when price alert triggers."""
    notify_user(
        username,
        "price_alert",
        {
            "keywords": alert_data.get("keywords"),
            "threshold_price": alert_data.get("threshold_price"),
            "listing": alert_data.get("listing"),
            "message": f"Price alert triggered for {alert_data.get('keywords')}",
        },
    )


def notify_saved_search_results(username: str, search_name: str, results_count: int) -> None:
    """Notify user when saved search finds new results."""
    notify_user(
        username,
        "saved_search",
        {
            "search_name": search_name,
            "results_count": results_count,
            "message": f"Your saved search '{search_name}' found {results_count} new listings",
        },
    )


def broadcast_system_message(message: str, level: str = "info", *, from_bus: bool = False, timestamp: Optional[str] = None) -> None:
    """Broadcast a system-wide message."""
    timestamp_value = timestamp or datetime.utcnow().isoformat() + "Z"
    if not from_bus:
        _publish_event("system.message", {"message": message, "level": level, "timestamp": timestamp_value})
    if socketio:
        try:
            socketio.emit(
                "system_message",
                {
                    "message": message,
                    "level": level,
                    "timestamp": timestamp_value,
                },
                namespace="/",
            )
            logger.info("Broadcast system message: %s", message)
        except Exception as exc:
            logger.error(f"Error broadcasting system message: {exc}")


def broadcast_dm_message(
    conversation_id: int,
    message: Dict[str, Any],
    sender: Optional[str] = None,
    *,
    from_bus: bool = False,
) -> None:
    """Broadcast a DM message to conversation participants."""
    if not from_bus:
        _publish_event("dm.message", {"conversation_id": conversation_id, "message": message, "sender": sender})
    if not socketio:
        return
    try:
        socketio.emit(
            "dm.message",
            {"conversation_id": conversation_id, "message": message, "sender": sender},
            room=f"dm_{conversation_id}",
        )
        _emit_dm_presence(conversation_id)
    except Exception as exc:
        logger.error(f"Error broadcasting DM message {message.get('id')}: {exc}")


def broadcast_dm_read_receipt(
    conversation_id: int,
    username: str,
    message_id: int,
    *,
    from_bus: bool = False,
) -> None:
    """Broadcast read receipt updates to conversation participants."""
    payload = {
        "conversation_id": conversation_id,
        "username": username,
        "message_id": message_id,
        "read_at": datetime.utcnow().isoformat() + "Z",
    }
    if not from_bus:
        _publish_event("dm.read", payload)
    if not socketio:
        return
    try:
        socketio.emit("dm.read", payload, room=f"dm_{conversation_id}", include_self=False)
        _emit_dm_presence(conversation_id)
    except Exception as exc:
        logger.error(f"Error broadcasting DM read receipt: {exc}")


def broadcast_dm_reaction(
    conversation_id: int,
    message_id: int,
    reactions: List[Dict[str, Any]],
    *,
    from_bus: bool = False,
) -> None:
    """Broadcast updated reaction state for a message."""
    payload = {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "reactions": reactions,
    }
    if not from_bus:
        _publish_event("dm.reaction", payload)
    if not socketio:
        return
    try:
        socketio.emit("dm.reaction", payload, room=f"dm_{conversation_id}")
    except Exception as exc:
        logger.error(f"Error broadcasting DM reactions for message {message_id}: {exc}")


def broadcast_channel_typing(
    channel_id: int,
    username: str,
    expires_at: datetime,
    *,
    is_typing: bool = True,
    from_bus: bool = False,
) -> None:
    payload = {
        "channel_id": channel_id,
        "username": username,
        "expires_at": expires_at.isoformat() + "Z",
        "typing": is_typing,
    }
    if not from_bus:
        _publish_event("channel.typing", payload)
    if not socketio:
        return
    try:
        socketio.emit(
            "channel.typing",
            payload,
            room=f"channel_{channel_id}",
            include_self=False,
        )
    except Exception as exc:
        logger.error(f"Error broadcasting channel typing state: {exc}")


def broadcast_dm_typing(
    conversation_id: int,
    username: str,
    expires_at: datetime,
    *,
    is_typing: bool = True,
    from_bus: bool = False,
) -> None:
    """Broadcast typing indicator state."""
    payload = {
        "conversation_id": conversation_id,
        "username": username,
        "expires_at": expires_at.isoformat() + "Z",
        "typing": is_typing,
    }
    if not from_bus:
        _publish_event("dm.typing", payload)
    if not socketio:
        return
    try:
        socketio.emit("dm.typing", payload, room=f"dm_{conversation_id}", include_self=False)
    except Exception as exc:
        logger.error(f"Error broadcasting DM typing state: {exc}")


def broadcast_dm_presence(conversation_id: int) -> None:
    """Broadcast participant presence snapshot for a conversation."""
    _emit_dm_presence(conversation_id)


# ======================
# HELPER FUNCTIONS
# ======================

def reserve_channel_message_slot(channel_id: int, username: str, interval_seconds: int, server_id: Optional[int] = None) -> None:
    """Reserve the right for a user to post in a channel, enforcing slow mode."""
    if interval_seconds <= 0:
        return

    now = time.time()
    key = f"realtime:slowmode:{channel_id}:{username}"

    def _redis_reserve(client: "redis.Redis") -> Optional[float]:
        if client.setnx(key, now):
            client.expire(key, interval_seconds)
            return None
        ttl = client.ttl(key)
        if ttl is None or ttl < 0:
            ttl = interval_seconds
            client.expire(key, interval_seconds)
        return float(ttl)

    sentinel = object()
    ttl_remaining = _with_redis("slowmode.reserve", _redis_reserve, default=sentinel)
    if ttl_remaining is not sentinel:
        if ttl_remaining is None:
            return
        try:
            db_enhanced.record_slow_mode_violation(server_id, channel_id, username, ttl_remaining)
        except Exception as exc:
            logger.debug(f"Failed to record slow mode violation: {exc}")
        raise SlowModeViolation(float(ttl_remaining))
    # If Redis was unavailable or circuit open, fall back to in-memory cache

    with _slow_mode_lock:
        cache_key = (channel_id, username)
        expires_at = _slow_mode_cache.get(cache_key, 0)
        if expires_at > now:
            retry_after = expires_at - now
            try:
                db_enhanced.record_slow_mode_violation(server_id, channel_id, username, retry_after)
            except Exception as exc:
                logger.debug(f"Failed to record slow mode violation (fallback): {exc}")
            raise SlowModeViolation(expires_at - now)
        _slow_mode_cache[cache_key] = now + interval_seconds


def get_connected_users() -> int:
    """Return the number of active websocket connections."""
    if socketio:
        try:
            return len(socketio.server.manager.get_participants("/", None))  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - depends on socketio internals
            pass
    return 0


__all__ = [
    "init_socketio",
    "socketio",
    "broadcast_new_listing",
    "notify_user",
    "broadcast_scraper_status",
    "notify_price_alert_triggered",
    "notify_saved_search_results",
    "broadcast_system_message",
    "broadcast_dm_message",
    "broadcast_dm_read_receipt",
    "broadcast_dm_reaction",
    "broadcast_channel_typing",
    "broadcast_dm_typing",
    "broadcast_dm_presence",
    "get_realtime_health",
    "reserve_channel_message_slot",
    "SlowModeViolation",
    "get_connected_users",
]

