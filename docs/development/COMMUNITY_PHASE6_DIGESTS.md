# Phase 6 – Owner Digests & Ops

## Overview
- Weekly digest pipeline summarises community health for server owners.
- Metrics are sourced from the analytics layer to keep reporting consistent.
- Admin tooling can queue, inspect, and mark digests as delivered for ops workflows.

## Backend Highlights
- Added `server_owner_digests` table to persist generated payloads, status, and delivery metadata.
- Digest composition leverages `compute_server_owner_digest(server_id, period_days)` which combines:
  - New members (count + roster) for the period.
  - Message volume, active senders, top contributors, and busiest channels.
  - Outstanding moderation load (open reports + new reports logged).
  - Analytics snapshot to align with `/api/servers/<slug>/analytics` responses.
- Helper APIs:
  - `enqueue_server_owner_digest` queues the payload for delivery.
  - `list_server_owner_digests`, `get_pending_owner_digests`, `mark_server_owner_digest_delivered` support ops workflows.

## API Surface
- `GET /api/servers/<slug>/digest/preview` – owner/mod/admin preview of the upcoming digest window.
- `GET /api/servers/<slug>/digests` – historical digests with status filtering.
- `POST /api/servers/<slug>/digests` – queue on-demand digest (owner/admin).
- `GET /api/ops/digests/pending` – admin view of pending queue.
- `POST /api/ops/digests/run` – batch mark oldest pending digests as delivered.
- `POST /api/ops/digests/<id>/deliver` – manual success/failure updates with optional failure reason.

## Verification
1. `pytest tests/test_community_servers.py -k digest` – validates digest computation + queue workflow.
2. Hit preview endpoint as owner; verify highlights, metrics, and analytics snapshot mirror server analytics.
3. Queue digest and confirm entry appears in `/api/ops/digests/pending` then transitions to delivered via ops endpoint.

## Follow-ups / Notes
- Messages and report aggregations respect the requested window (default 7 days, max 90).
- Delivery channel stored for future multi-channel support; currently defaults to `email`.
- Admin run endpoint intentionally idempotent: skips digests that fail to update and logs errors.

