# Community UI Phase 4 – Front-End Integration Notes

This document captures the UI work completed in Phase 4 together with the guardrails and manual QA steps you should follow when exercising the new flows.

## 1. Friend List Integration

- **Endpoint**: `GET /api/profile/<username>/friends` (cursor-based pagination).
- **Entry Point**: Profile page → Connections card → “Friends” section.
- **UI behaviour**
  - Initial list seeds from `GET /api/friends/overview`.
  - “Load more friends” button appears once `overview.next_cursor` is present; subsequent pages append to the list.
  - Inline error messaging (`#friendsError`) appears if pagination fails, without clearing already loaded rows.
  - Counter badges (`#friendCountBadge`) reflect server-provided totals (`counts.friends`).
- **Visibility**: Server sends only records the viewer is allowed to see; the UI does not surface restricted friends.

## 2. Reporting Controls

- **Profile Report**
  - Button: header action bar → “Report Profile”.
  - Hidden when viewing your own profile.
  - Posts `POST /api/reports` with `target_type: "profile"` and the prompted reason string.
  - Toast notifications confirm submission or surface API errors.

- **Channel Message Report**
  - Each channel message now includes a “Report” action.
  - Prompt captures the reason, then posts `POST /api/reports` with `target_type: "channel_message"` plus channel/server context (`channel_slug`, `server_slug`, `sender`).
  - Composer status line is reused for success/error feedback so users stay informed when slow-mode prevents immediate retries.

## 3. Realtime Channel UI

- **Authentication**
  - The websocket client retrieves `/api/realtime/token` before opening Socket.IO and refreshes expiring tokens automatically.

- **Channel Presence**
  - Connecting to a channel page triggers `channel.join` and begins receiving `channel.presence` snapshots.
  - Presence list renders up to six users with self-highlighting pills and a `+N` overflow marker.
  - Disconnects or navigation emit `channel.leave`, removing the user from shared presence.

- **Typing Indicators**
  - Composer emits throttled `channel.typing` signals (at most once every 3 s) whenever the textarea gains focus or updates.
  - Incoming typing events populate an in-memory TTL map; the typing banner maintains the pencil icon while rotating text (`You`, `@user`, `@user and @other`, etc.).
  - Redis persists typing states when available; the UI gracefully falls back to per-tab behaviour if Redis is down.

- **Slow Mode Feedback**
  - Client renders the configured slow-mode duration in the header.
  - When a 429 response is received, the composer status shows the server-provided message and starts a countdown timer before re-enabling input.

## 4. Manual QA Checklist

Run these steps in a local environment (Redis optional but recommended):

1. **Friend List Pagination**
   - Visit a profile with > 25 friends.
   - Check initial count badges, click “Load more friends”, ensure new rows append and button hides when exhausted.
   - Disconnect network before clicking “Load more” to confirm inline error handling.

2. **Profile Reporting**
   - Visit another user’s profile, click “Report Profile”, submit a reason.
   - Validate a success toast appears; repeat with an empty reason to ensure cancellation messaging.

3. **Channel Reporting & Slow Mode**
   - In a channel with slow-mode enabled, submit a message twice inside the cooldown and confirm the countdown UI appears.
   - Use the “Report” action on a message and verify composer feedback.

4. **Presence/Typing (with Redis)**
   - Open the same channel in two browsers/logins.
   - Confirm presence pills update as each user joins/leaves.
   - Type simultaneously and verify typing banner updates (with pluralisation) and clears shortly after both users stop.

5. **Presence/Typing (without Redis)**
   - Stop Redis or unset `REALTIME_REDIS_URL`.
   - Repeat the typing/presence test to ensure behaviour still works with per-process caches (expect scope limited to a single worker).

6. **Token Expiry**
   - Shorten `REALTIME_JWT_TTL_SECONDS` (e.g., to 30) and confirm the websocket reconnects automatically without manual refresh.

7. **Regression Smoke**
   - Check that the pre-existing dashboard websocket notifications still flow (new listing, scraper status) since we replaced the JS client.

## 5. Analytics & Health Dashboards

- **Server insights** (`GET /api/servers/<slug>/analytics`, mod/owner only)
  - Metrics: member totals, recent joins (7-day + configurable window), message volume, active senders, top channels, slow-mode coverage, open report breakdown.
  - Query params: `days` (1–365, default 30).
- **Community health** (`GET /api/analytics/community`, admin only)
  - Metrics: total/new/active servers, membership growth, message throughput, report load, top topic tags, generated timestamp.
- **Implementation notes**
  - Back-end aggregators: `db_enhanced.get_server_analytics(server_id, days)` and `db_enhanced.get_community_analytics(days)`.
  - Feed events now emit `summary` and `computed_score` to aid ranking.
  - Discovery payloads expose `discovery_score` and `is_new` so UI can highlight trending servers.

### Testing Status

Automated coverage now includes discovery, feed ranking, DM management, and analytics paths:

```bash
pytest tests/test_community_servers.py
```

(SQLite still emits Python 3.13 datetime adapter deprecation warnings; see `sqlite3` docs for adapter migration.)
