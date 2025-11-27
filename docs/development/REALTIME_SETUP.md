<!-- Real-Time Infrastructure Setup Guide -->

# Real-Time Infrastructure Setup

This document describes how to configure the Redis-backed realtime stack and WebSocket authentication introduced in Phase 3.

## 1. Environment Variables

Set the following variables in `.env` (or your deployment environment):

| Variable | Purpose | Default |
| --- | --- | --- |
| `REALTIME_REDIS_URL` | Connection string for the Redis instance used for presence, typing indicators, and slow-mode tracking. | Disabled when unset |
| `REALTIME_JWT_SECRET` | Secret used to sign realtime (WebSocket) JWTs. | Falls back to `SECRET_KEY` |
| `REALTIME_JWT_TTL_SECONDS` | Lifetime (seconds) of issued realtime tokens. | `300` |
| `REALTIME_JWT_AUDIENCE` | Audience claim required on realtime tokens. | `superbot-realtime` |
| `REALTIME_JWT_ISSUER` | Issuer claim applied to realtime tokens. | `superbot` |

If you are reusing the primary Flask secret for realtime tokens, you can omit `REALTIME_JWT_SECRET`.

## 2. Redis Requirements

Redis powers:

- Presence snapshots and typing indicators (with TTL-backed keys)
- Channel slow-mode enforcement
- Realtime event bus fan-out across multiple workers

Recommended configuration:

```bash
docker run -d \
  --name superbot-redis \
  -p 6379:6379 \
  redis:7-alpine \
  redis-server --save 60 1000 --loglevel warning
```

Use `redis-cli ping` to confirm connectivity, then set `REALTIME_REDIS_URL=redis://localhost:6379/0`.

### Graceful Fallback

If Redis is unavailable or the Python `redis` package is not installed:

- Presence and typing indicators fall back to in-process caches (per worker)
- Slow-mode enforcement falls back to an in-memory throttler
- Event bus fan-out is disabled (each worker only notifies its own connections)

Log messages explicitly note when Redis is disabled.

## 3. WebSocket Authentication

### Issuing Tokens

Clients must request a realtime JWT before establishing a Socket.IO connection:

```
POST /api/realtime/token
```

The response includes `token` and `expires_in`. Tokens embed the user's server memberships to support capability checks at the edge.

### Connecting

Supply the token as a query parameter when opening the Socket.IO connection:

```javascript
const socket = io('/', { query: { token } });
```

Connections that omit a valid token (or present a mismatched session) are rejected with `authentication_required` / `invalid_token`.

## 4. Slow-Mode Enforcement

Channel metadata (`channel.settings.slow_mode`) defines the per-user cooldown in seconds. On each message:

1. The API calls `reserve_channel_message_slot(...)`
2. Redis coordinates cooldowns across workers (with an in-memory fallback)
3. A `SlowModeViolation` triggers a `429` response with the remaining wait time

## 5. Operational Notes

- Restarting all workers clears in-memory fallback caches. Redis-backed data survives restarts.
- The realtime event listener runs in a daemon thread; monitor logs for warnings such as `Realtime event listener stopped unexpectedly`.
- Install the new dependencies (`redis` and `PyJWT`) before deploying:

```bash
pip install -r requirements.txt
```

With these steps in place, multiple application workers share presence state, slow-mode timing, and websocket broadcasts through Redis, while secured tokens ensure that only authorized users can establish realtime connections.


