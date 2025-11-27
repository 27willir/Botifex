<!-- Social & Community Feature Specification -->

# Social & Community Specification

## 1. Data Foundations & Real-Time Infrastructure

### 1.1 Core Tables

| Table | Key Fields | Notes |
| --- | --- | --- |
| `profiles` | `user_id (PK)`, `display_name`, `bio`, `avatar_url`, `banner_url`, `gender`, `pronouns`, `location`, `search_interests (jsonb)`, `showcase_config (jsonb)`, `visibility_settings (jsonb)`, `created_at`, `updated_at` | Replaces or extends existing user profile table. `visibility_settings` stores per-field public/private flags. |
| `profile_activity` | `id (PK)`, `user_id`, `activity_type`, `entity_id`, `metadata (jsonb)`, `occurred_at` | Powers recent activity feed sections and recommendations. |
| `profile_showcase_items` | `id (PK)`, `user_id`, `collection_type`, `entity_id`, `label`, `position`, `metadata (jsonb)`, `added_at`, `updated_at` | Normalized store for showcase slots (favorite searches, listings, servers). `collection_type` enum: `search`, `listing`, `server`. |
| `servers` | `id (PK)`, `owner_id`, `name`, `slug`, `description`, `topic_tags (text[])`, `visibility`, `icon_url`, `banner_url`, `settings (jsonb)`, `created_at` | `settings` holds slow-mode defaults, keyword filters, etc. |
| `server_roles` | `id (PK)`, `server_id`, `name`, `permissions (jsonb)`, `is_default`, `created_at` | Supports custom role matrices. Bootstrap roles `owner`, `moderator`, `member`. |
| `server_memberships` | `server_id`, `user_id`, `role_id`, `status`, `joined_at`, `invited_by`, `last_active_at` | Composite PK (`server_id`, `user_id`). Status enumerates `active`, `pending`, `banned`. |
| `channels` | `id (PK)`, `server_id`, `type`, `name`, `slug`, `topic`, `position`, `settings (jsonb)`, `created_at` | Channel types: `text`, `announcement`, `marketplace`. |
| `messages` | `id (PK)`, `channel_id`, `sender_id`, `body`, `rich_content (jsonb)`, `message_type`, `thread_root_id`, `created_at`, `edited_at`, `deleted_at` | For DM channels, `channel_id` references DM conversation records (see §1.2). |
| `message_reactions` | `message_id`, `user_id`, `reaction_type`, `created_at` | Composite PK (`message_id`, `user_id`, `reaction_type`). |
| `dm_conversations` | `id (PK)`, `type`, `created_at`, `last_message_at` | Type: `direct`, `group`. |
| `dm_participants` | `conversation_id`, `user_id`, `role`, `joined_at`, `left_at` | Composite PK (`conversation_id`, `user_id`). Role handles admin privileges for group DMs. |
| `dm_messages` | `id (PK)`, `conversation_id`, `sender_id`, `body`, `rich_content (jsonb)`, `created_at`, `edited_at`, `deleted_at` | Separate table for performance isolation if DM load differs from server channels. |
| `attachments` | `id (PK)`, `message_id`, `storage_key`, `type`, `metadata (jsonb)`, `created_at` | `type` indicates `image`, `listing`, `link`. |
| `server_invites` | `id (PK)`, `server_id`, `created_by`, `code`, `expires_at`, `max_uses`, `uses`, `metadata (jsonb)` | `metadata` tracks invite channel, campaign tags. |
| `moderation_actions` | `id (PK)`, `server_id`, `actor_id`, `action_type`, `target_id`, `target_type`, `reason`, `metadata (jsonb)`, `created_at` | Feeds audit logs and escalation tooling. |
| `reports` | `id (PK)`, `reporter_id`, `target_type`, `target_id`, `context (jsonb)`, `status`, `created_at`, `resolved_at` | Escalates to moderators or site admins. |
| `feed_events` | `id (PK)`, `event_type`, `actor_id`, `entity_type`, `entity_id`, `payload (jsonb)`, `score`, `created_at` | Stores atomic events to hydrate feeds and notifications. |
| `notifications` | `id (PK)`, `user_id`, `event_id`, `notification_type`, `payload (jsonb)`, `delivery_status`, `created_at`, `seen_at` | Drives notification center and push/email. |
| `friend_requests` | `id (PK)`, `requester_id`, `recipient_id`, `status`, `message`, `created_at`, `responded_at` | `status`: `pending`, `accepted`, `declined`, `cancelled`; soft delete to retain audit history. |
| `friendships` | `user_id`, `friend_id`, `created_at`, `source_request_id` | Composite PK (`user_id`, `friend_id`). Store undirected friendships as two mirrored rows. |

### 1.2 Relationships & Indexing

- Foreign keys with cascading deletes limited to user-driven artifacts (e.g. deleting a server cascades to channels and memberships but archives messages for compliance).
- Add unique partial index on `friend_requests (requester_id, recipient_id)` filtering `status = 'pending'` to prevent duplicate outstanding requests; enforce requester != recipient at DB layer.
- Maintain covering index on `friendships (user_id, created_at)` for fast friend list retrieval; cascade deletes when users deactivate via scheduled cleanup job to preserve request history.
- Partition high-volume tables (`messages`, `dm_messages`, `feed_events`) by month to simplify retention policies.
- Maintain GIN indexes on JSONB columns (`search_interests`, `payload`) for filtering.
- Materialized views for feeds (e.g. per-server top threads) with scheduled refresh via Celery/Redis Queue.

### 1.3 Real-Time Architecture

- **WebSocket Gateway**: FastAPI + `uvicorn` service issuing short-lived JWT tokens tied to server roles.
- **Presence & Typing**: Redis pub/sub channels keyed by `channel:{id}`; store ephemeral user state with TTL 60s.
- **Message Fan-out**: Write path hits Postgres via async worker; publish event to NATS or Redis Stream that notifies subscribers and fan-outs to push/email queue.
- **Social Events**: Friend request create/update events publish over WebSocket channels keyed by `user:{id}:friends` to update pending counts and presence gating in real time.
- **Backpressure**: Apply rate limits via Redis token bucket keyed by user+channel for slow-mode enforcement.
- **Failover**: Graceful fallback to long-polling if WebSocket unsupported; instrument with Prometheus metrics.

## 2. Profile Revamp Experience

### 2.1 User Journeys

- **Onboarding**: After signup, modal surfaces critical fields (`display_name`, `avatar`, `interests`) with progress meter.
- **Profile Editor**: Two-column layout—left navigation (Basics, Identity, Interests, Visibility, Showcase), right pane with live preview.
- **Profile Viewer**: Public view displays banner, avatar, pronouns, location, interest chips, recent activity module, and showcase cards.
- **Connections**: Dedicated tab on profile for managing friends, pending requests, and mutual connections.

### 2.2 UI Components

- `ProfileForm`: React-style component using existing template system; handles validation, autosave drafts.
- `MediaUploader`: Reusable for avatar/banner. Integrates with S3 pre-signed uploads, image cropping, moderation hook.
- `VisibilityToggle`: Per-field switch tied to `visibility_settings` map.
- `ShowcaseBuilder`: Drag-and-drop for ordering listings, searches, joined servers.

### 2.3 API Contracts

- `GET /api/profile/:userId` returns sanitized fields respecting viewer permissions.
- `PUT /api/profile/:userId` accepts partial updates with permission checks.
- `POST /api/profile/media/sign` returns upload URL and CDN path; triggers asynchronous moderation scan.
- `GET /api/profile/:userId/activity` paginated recent actions.
- `POST /api/profile/:userId/friend-request` creates pending request; rate limited and validates block lists/mutual requirement settings.
- `POST /api/friends/:requestId/respond` accepts or declines; acceptance writes mirrored records to `friendships` and emits notifications.
- `DELETE /api/friends/:friendId` removes friendship for both users; archives related DM conversation history to read-only state.

### 2.4 Search Integration

- Index `display_name`, `bio`, `interests`, `location` in Elastic/OpenSearch.
- Add faceted filters: location, pronouns (aggregate-safe), interests, active servers presence.

### 2.5 Enhanced Profile Fields

- `avatar_url` and `banner_url`: enforce 2 MB upload max, minimum 512×512 resolution, crop UI supports 1:1 and 3:1 aspect ratios.
- `display_name`: 3–40 characters, unicode allowed with server-side normalization to prevent spoofing.
- `bio`: 280-character hard cap, lightweight Markdown (`*italic*`, `**bold**`, links). Abuse filters run on save.
- `gender`/`pronouns`: optional fields—support dropdown presets plus free-form input with 30-character limit each.
- `location`: powered by Mapbox autocomplete; store city-level plus country code for faceting.
- `search_interests`: JSON array of `{ id, label, category }`; max 12 chips displayed as clickable badges.
- `recent_activity`: surfaces last 10 `profile_activity` entries filtered by viewer permissions (hide joined private servers).

### 2.6 Visibility & Privacy Rules

- Each top-level field maps to `visibility_settings[field_key] = public|connections|private`; defaults: `display_name`, `avatar` public; all others `connections`.
- Profile editor groups toggles into `About` (display name, pronouns, location, bio), `Interests`, `Showcase`, `Activity`.
- Public vs private sections: in public view, collapse hidden fields into “Private to you” placeholder; connections inherit intermediate visibility.
- API enforces visibility at serialization layer; auditors log visibility changes in `profile_activity` for compliance review.
- Allow quick toggle “Hide entire profile” to mark all non-required fields private until re-enabled.

### 2.7 Showcase Collections

- Collections supported: `favorite_searches`, `featured_listings`, `servers_joined`; each user can surface up to 3 cards per collection.
- `ShowcaseBuilder` writes ordered items to `profile_showcase_items` while caching layout in `profiles.showcase_config` (`{ collection_key: [item_id...] }`).
- Each showcase card includes thumbnail, title, optional note; note stored in `metadata.note` with 80-character limit.
- View layer respects visibility toggles per collection; if all items hidden, suppress section header.
- Server-side validation ensures referenced entities exist and user has rights (e.g., joined server membership).

### 2.8 Friend Connections

- Profile surfaces `Add Friend`, `Cancel Request`, or `Accept/Decline` CTA based on relationship state; actions respect visibility toggles (`visibility_settings.connections`).
- `Connections` tab lists accepted friends with mutual server badges, pending outgoing requests, and incoming requests.
- Friend list paginates via `GET /api/profile/:userId/friends?cursor=...`; response includes `friendship_status`, `mutual_count`, and latest activity snippet.
- Users can add an optional short message (140 chars) when sending a friend request; stored in `friend_requests.message`.
- Privacy options allow auto-decline invites from non-mutual servers or require shared server membership (configurable under profile settings).

## 3. Messaging MVP

### 3.1 Conversation Lifecycle

1. Client requests or creates DM conversation (`POST /api/dm/conversations`) with participants once a mutual friendship exists.
2. Server validates friendship state (mirror rows in `friendships`), block lists, DM rate limits, and conversation membership limits; pending requests return `409` with guidance to accept first.
3. Messages post over WebSocket (`event:dm_message:new`) or REST fallback (`POST /api/dm/messages`).
4. Delivery pipeline stores message, publishes to conversation stream, updates unread counts, schedules notifications.

### 3.2 Reactions & Read Receipts

- Reactions share schema with server messages to enable emoji set reuse.
- Read receipts stored in `dm_participants.last_read_message_id`; broadcast delta updates to conversation members.
- Typing indicators broadcast ephemeral events via Redis pub/sub.

### 3.3 Attachments & Inline Items

- Inline marketplace items stored as attachment type `listing`; payload references listing ID and snapshot metadata.
- URL enrichment service fetches OpenGraph previews with caching.
- Saved searches shareable by embedding `search_id` and label; recipients can subscribe directly from message.

### 3.4 Direct & Group Messaging

- Real-time 1:1 chats and small ad-hoc groups.
- Inline item sharing, saved searches, quick reply templates.
- Message reactions, read receipts, typing indicators.
- Typing indicators emit `dm.typing` events with 6s TTL; gateway auto-expires stale signals and fans out to active participants.
- Presence badges surface per-user “last active” based on recent message activity and read receipts cached in Redis.
- DM compose entry points prompt users to send/accept friend requests if no `friendships` record exists; pending state disables message composer but allows request follow-up.

### 3.5 Notifications

- Push/email triggered by event worker respecting quiet hours and batching preferences.
- Notification templates differentiate between direct mentions, new DM, and reactions.
- Web client surfaces unread badge counts based on `notifications` table.
- New notification types: `friend_request_received`, `friend_request_accepted`; support in-app and email fallback with respect for privacy preferences.

### 3.6 Security Considerations

- Endpoints enforce server-side profanity filter for uploads and message body.
- Implement suspicious DM heuristics (e.g., repeated links, high-frequency invites) with automatic rate limiting.

## 4. Server Experience

### 4.1 Server Lifecycle

- `POST /api/servers` creates server, bootstrap default roles, generate vanity invite.
- `POST /api/servers/:id/invite` issues invite links; optional approval setting toggles join requests.
- `POST /api/servers/:id/join` uses invite code or discovery join; respects bans and pending approvals.

### 4.2 Channel UX

- Navigation tree grouped by channel type; supports drag-and-drop reordering.
- Text channels support Markdown (limited to bold/italic, code fence, lists), emoji picker, thread replies via `thread_root_id`.
- Announcement channels support formatting guardrails and optional cross-post to server feed.

### 4.3 Moderation Dashboards

- Table view of members with filters (role, join date, flags).
- Quick actions: assign role, mute, kick/ban, enable slow mode.
- Audit log viewer paginated with search by actor/target/action.
- Keyword filter management: allow mods to add phrases, set severity (block vs flag).

### 4.4 Permissions Model

- Permission matrix stored on `server_roles.permissions`; defines capabilities (`manage_channels`, `ban_members`, `post_announcements`, etc).
- Effective permissions computed by union of role assignments; cached per user+server in Redis with 5 min TTL.
- Capability checks enforced in WebSocket gateway handshake and REST endpoints.

## 5. Discovery & Feed Systems

### 5.1 Server Directory

- `GET /api/servers/discover` supports query, topic filters, location facet, and personalization token.
- Ranking formula combines server growth, engagement, and profile-interest overlap.
- Trending cache refreshed every 10 minutes using incremental aggregation job.

### 5.2 Home Feed

- Unified feed pulls from `feed_events` with composition rules:
  - Server highlights (top threads, announcements).
  - DM mentions or saved search alerts.
  - Marketplace listing recommendations aligned with interests.
- Feed hydration pipeline:
  1. Event ingestion writes to `feed_events`.
  2. Scoring job calculates `score` with decay.
  3. User-specific view filters events based on memberships and privacy settings.

### 5.3 Notification Center

- `GET /api/notifications` returns grouped results (Today, Earlier).
- Allows per-notification dismissal, mark-all-read, and preference toggles (email vs push vs in-app).
- Integrates with browser push (VAPID) and mobile push providers.

### 5.4 Recommendation Engine

- Input signals: profile interests, saved searches, recent activity, server memberships, listing interactions.
- Hybrid approach: TF-IDF keyword vectors + optional embeddings (SBERT) stored in vector index (pgvector).
- Cold start fallback uses curated featured servers and staff picks.

### 5.5 Feed & Activity Layer

- Unified home feed mixing server highlights, DM mentions, listing alerts.
- Server-specific feeds showing hot threads, member spotlights.
- Notification center for mentions, invites, boosts.

## 6. Moderation, Safety & Analytics

### 6.1 Advanced Moderation

- Slow-mode: configurable per channel; enforced via Redis timestamp check.
- Keyword filters: allow block, warn, or auto-report; integrate with message processing pipeline.
- Reporting workflow:
  1. User submits report (`POST /api/reports`).
  2. Triage queue for server mods; escalate to site admins based on severity or inactivity.
  3. Resolution updates status and notifies reporter.

### 6.2 Safety Automation

- Block/ignore lists ensure DM initiation is prevented and server mentions muted.
- Abuse detection pipeline scans for spam patterns, new user probation.
- Image moderation via third-party service; quarantine flagged media pending review.
- Friend request throttling ties into abuse heuristics (per-user/day caps, auto-block spammers); pending requests auto-expire after 30 days to reduce stale data.

### 6.3 Analytics & Health

- Metrics dashboards: server growth, retention, active members, message volume, moderation actions.
- Use Segment/Amplitude event tracking; align with `feed_events` schema for consistency.
- Weekly digest for server owners summarizing new members, top channels, outstanding reports.

### 6.4 Performance & Reliability

- CDN-backed delivery for avatars/banners with automatic resizing.
- Background jobs for search indexing, feed scoring, notification fan-out.
- Regular load testing of WebSocket throughput; autoscale gateway pods based on concurrent connections.

## 7. Open Questions & Next Steps

- Confirm privacy compliance requirements for storing gender/pronoun data in specific regions.
- Decide on persistence duration for deleted messages and audit log retention.
- Align on target clients (web/mobile parity) for MVP scope.
- Determine default policy for friend request eligibility (mutual server requirement vs open network) and region-specific consent flows.
- Prototype UX wireframes and validate with stakeholders before implementation sprint.


