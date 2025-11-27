import os
import sys
import shutil
import tempfile
import importlib
import unittest
from datetime import datetime, timedelta


class CommunityServersTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.mkdtemp(prefix="servers_test_")
        cls.db_path = os.path.join(cls._temp_dir, "community.db")
        os.environ["DB_FILE"] = cls.db_path
        if "db_enhanced" in sys.modules:
            cls.db = importlib.reload(sys.modules["db_enhanced"])
        else:
            cls.db = importlib.import_module("db_enhanced")
        cls.db.close_database()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.db.close_database()
        finally:
            shutil.rmtree(cls._temp_dir, ignore_errors=True)

    def setUp(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db.init_db()
        self.db.create_user_db("owner", "owner@example.com", "hash")
        self.db.ensure_profile("owner")

    def tearDown(self):
        self.db.close_database()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _create_member(self, username):
        self.db.create_user_db(username, f"{username}@example.com", "hash")
        self.db.ensure_profile(username)

    def test_server_creation_bootstraps_defaults(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Vintage Finds Hub",
            description="A place to trade vintage goods.",
            topic_tags=["vintage", {"label": "garage sales"}],
            visibility="public",
        )

        self.assertEqual(server["name"], "Vintage Finds Hub")
        self.assertEqual(server["owner_username"], "owner")
        self.assertEqual(server["visibility"], "public")

        channels = self.db.get_server_channels(server["id"])
        self.assertGreaterEqual(len(channels), 3)

        roles = self.db.get_server_roles(server["id"])
        role_names = {role["name"] for role in roles}
        self.assertIn("Owner", role_names)
        self.assertIn("Member", role_names)

        membership = self.db.get_server_membership(server["id"], "owner", include_permissions=True)
        self.assertIsNotNone(membership)
        self.assertEqual(membership["status"], "active")
        permissions = membership.get("permissions") or {}
        self.assertTrue(permissions.get("manage_server", False))

    def test_join_server_workflow(self):
        public_server = self.db.create_server(
            owner_username="owner",
            name="Public Deals",
            topic_tags=["deals", "local"],
            visibility="public",
        )

        private_server = self.db.create_server(
            owner_username="owner",
            name="Private Drops",
            topic_tags=["exclusive"],
            visibility="private",
        )

        self._create_member("member")
        public_join = self.db.join_server(public_server["slug"], "member")
        self.assertTrue(public_join["activated"])
        self.assertEqual(public_join["membership"]["status"], "active")

        self._create_member("scout")
        pending_join = self.db.join_server(private_server["slug"], "scout")
        self.assertFalse(pending_join["activated"])
        self.assertEqual(pending_join["membership"]["status"], "pending")

        requests = self.db.list_server_pending_requests(private_server["id"], "owner")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["username"], "scout")

        invite = self.db.create_server_invite(private_server["id"], created_by="owner", expires_in_hours=12, max_uses=2)
        self._create_member("collector")
        invited_join = self.db.join_server(private_server["slug"], "collector", invite_code=invite["code"])
        self.assertTrue(invited_join["activated"])
        self.assertEqual(invited_join["membership"]["status"], "active")

        decision = self.db.respond_to_join_request(private_server["id"], "owner", "scout", approve=True)
        self.assertEqual(decision["status"], "active")
        scout_membership = self.db.get_server_membership(private_server["id"], "scout")
        self.assertEqual(scout_membership["status"], "active")

    def test_server_directory_lists_all_servers(self):
        self.db.create_server(
            owner_username="owner",
            name="Collector Cars HQ",
            topic_tags=["cars", "auctions"],
            visibility="public",
        )
        self.db.create_server(
            owner_username="owner",
            name="Private Wholesale Network",
            topic_tags=["wholesale"],
            visibility="private",
        )

        all_servers = self.db.get_all_servers()
        names = {srv["name"] for srv in all_servers}
        self.assertIn("Collector Cars HQ", names)
        self.assertIn("Private Wholesale Network", names)

    def test_channel_messages_lifecycle(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Chat Lounge",
            visibility="public",
        )
        channels = self.db.get_server_channels(server["id"])
        self.assertGreater(len(channels), 0)
        default_channel = channels[0]

        # Owner sends a message
        message = self.db.create_channel_message(default_channel["id"], "owner", "Hello community!")
        self.assertEqual(message["body"], "Hello community!")
        self.assertEqual(message["sender_id"], "owner")
        self.assertEqual(message["message_type"], "text")
        self.assertIsInstance(message.get("attachments"), list)
        self.assertFalse(message.get("attachments"))
        self.assertIsInstance(message.get("reactions"), list)

        history = self.db.get_channel_messages(default_channel["id"], limit=10, viewer_username="owner")
        self.assertTrue(any(msg["body"] == "Hello community!" for msg in history))
        self.assertTrue(all("message_type" in msg for msg in history))


    def test_channel_message_with_attachments_and_reactions(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Media Lounge",
            visibility="public",
        )
        channels = self.db.get_server_channels(server["id"])
        default_channel = channels[0]

        attachment_payload = [{
            "storage_key": "uploads/example-link",
            "type": "link",
            "metadata": {"label": "Example"},
        }]

        message = self.db.create_channel_message(
            default_channel["id"],
            "owner",
            "",
            message_type="link",
            rich_content={"url": "https://example.com"},
            attachments=attachment_payload,
        )

        self.assertEqual(message["message_type"], "link")
        self.assertEqual(len(message.get("attachments", [])), 1)

        reactions = self.db.add_channel_message_reaction(message["id"], "owner", "🔥")
        self.assertTrue(any(r["reaction"] == "🔥" for r in reactions))

        fetched = self.db.get_channel_message(message["id"], viewer_username="owner")
        self.assertEqual(len(fetched.get("attachments", [])), 1)
        self.assertTrue(any(r["viewer_reacted"] for r in fetched.get("reactions", []) if r["reaction"] == "🔥"))

        remaining = self.db.remove_channel_message_reaction(message["id"], "owner", "🔥")
        self.assertFalse(any(r["reaction"] == "🔥" for r in remaining))


    def test_create_and_update_report(self):
        self._create_member("reporter")
        report = self.db.create_report("reporter", "message", "42", context={"reason": "spam"})
        self.assertEqual(report["status"], self.db.REPORT_STATUS_PENDING)

        fetched = self.db.get_report_by_id(report["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["target_id"], "42")

        updated = self.db.update_report_status(report["id"], self.db.REPORT_STATUS_RESOLVED)
        self.assertEqual(updated["status"], self.db.REPORT_STATUS_RESOLVED)

    def test_moderation_keyword_filters_and_reports_queue(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Moderation Station",
            visibility="public",
        )

        filters = self.db.get_server_keyword_filters(server["id"])
        self.assertEqual(filters, [])

        added = self.db.add_server_keyword_filter(server["id"], "spam", "block", created_by="owner")
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["action"], "block")

        updated = self.db.add_server_keyword_filter(server["id"], "spam", "warn", created_by="owner")
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["action"], "warn")

        remaining = self.db.remove_server_keyword_filter(server["id"], "spam")
        self.assertEqual(remaining, [])

        self._create_member("reporter")
        primary_report = self.db.create_report(
            "reporter",
            "channel_message",
            "101",
            context={"server_slug": server["slug"], "reason": "spam"},
        )
        other_server = self.db.create_server(
            owner_username="owner",
            name="Other Lounge",
            visibility="public",
        )
        self.db.create_report(
            "reporter",
            "channel_message",
            "202",
            context={"server_slug": other_server["slug"], "reason": "off-topic"},
        )

        pending_queue = self.db.list_reports(server_slug=server["slug"])
        self.assertEqual(pending_queue["total"], 1)
        self.assertEqual(pending_queue["reports"][0]["id"], primary_report["id"])

        resolved = self.db.update_report_status(primary_report["id"], self.db.REPORT_STATUS_RESOLVED)
        self.assertEqual(resolved["status"], self.db.REPORT_STATUS_RESOLVED)

        resolved_queue = self.db.list_reports(
            statuses=[self.db.REPORT_STATUS_RESOLVED],
            server_slug=server["slug"],
        )
        self.assertEqual(resolved_queue["total"], 1)
        self.assertEqual(resolved_queue["reports"][0]["status"], self.db.REPORT_STATUS_RESOLVED)

        self.db.log_moderation_action(
            server["id"],
            "owner",
            "report_status_updated",
            target_id=str(primary_report["id"]),
            metadata={"status": self.db.REPORT_STATUS_RESOLVED},
        )
        actions = self.db.list_moderation_actions(server["id"])
        self.assertGreaterEqual(actions["total"], 1)
        self.assertTrue(
            any(action["action_type"] == "report_status_updated" for action in actions["actions"])
        )

    def test_user_blocks_and_friend_request_throttle(self):
        self._create_member("sender")
        self._create_member("alice")
        self._create_member("bob")

        block_record = self.db.block_user("sender", "alice", reason="spam")
        self.assertEqual(block_record["blocked_username"], "alice")
        self.assertTrue(self.db.is_user_blocked("sender", "alice"))
        blocks = self.db.list_user_blocks("sender")
        self.assertEqual(blocks["total"], 1)

        with self.assertRaises(ValueError):
            self.db.create_friend_request("sender", "alice")
        with self.assertRaises(ValueError):
            self.db.create_friend_request("alice", "sender")

        with self.assertRaises(ValueError):
            self.db.ensure_dm_conversation_between("sender", "alice")

        self.assertTrue(self.db.unblock_user("sender", "alice"))
        self.assertFalse(self.db.is_user_blocked("sender", "alice"))

        # Re-block another user to test DM enforcement
        self.db.block_user("sender", "bob")
        with self.assertRaises(ValueError):
            self.db.ensure_dm_conversation_between("sender", "bob")
        self.db.unblock_user("sender", "bob")

        limit = self.db.FRIEND_REQUEST_THROTTLE_LIMIT
        recipients = []
        for idx in range(limit):
            recipient = f"recipient_{idx}"
            recipients.append(recipient)
            self._create_member(recipient)
            request, created = self.db.create_friend_request("sender", recipient)
            self.assertTrue(created)
            self.assertEqual(request["recipient_username"], recipient)

        extra_user = "recipient_extra"
        self._create_member(extra_user)
        with self.assertRaises(ValueError):
            self.db.create_friend_request("sender", extra_user)


    def test_moderation_keyword_suggestions_from_reports(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Moderation Suggestion Server",
            visibility="public",
        )
        slug = server["slug"]

        report_contexts = [
            {"server_slug": slug, "reason": "Massive crypto pump happening now"},
            {"server_slug": slug, "reason": "Join this crypto airdrop instantly"},
            {"server_slug": slug, "reason": "Pump coin frenzy and crypto drop"},
        ]

        for idx, context in enumerate(report_contexts, start=1):
            reporter = f"reporter_{idx}"
            self._create_member(reporter)
            self.db.create_report(
                reporter,
                "channel_message",
                str(400 + idx),
                context=context,
            )

        suggestions = self.db.get_moderation_keyword_suggestions(server["id"], window_hours=72, limit=5)
        terms = {entry["term"] for entry in suggestions}
        self.assertIn("crypto", terms)
        self.assertIn("pump", terms)

        self.db.add_server_keyword_filter(server["id"], "pump", "block", created_by="owner")
        filtered = self.db.get_moderation_keyword_suggestions(server["id"], window_hours=72, limit=5)
        filtered_terms = {entry["term"] for entry in filtered}
        self.assertNotIn("pump", filtered_terms)


    def test_moderation_actions_export(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Moderation Export Server",
            visibility="public",
        )
        server_id = server["id"]

        action_one = self.db.log_moderation_action(
            server_id,
            "owner",
            "ban_member",
            target_id="user123",
            target_type="user",
            reason="Terms violation",
            metadata={"duration": "permanent"},
        )
        action_two = self.db.log_moderation_action(
            server_id,
            "owner",
            "bulk_ban",
            target_id="user456",
            target_type="user",
            reason="Coordinated spam",
            metadata={"count": 5, "notes": "auto-escalated"},
        )

        export_all = self.db.get_moderation_actions_export(server_id)
        self.assertGreaterEqual(export_all["count"], 2)
        action_types = {row["action_type"] for row in export_all["actions"]}
        self.assertIn("ban_member", action_types)
        self.assertIn("bulk_ban", action_types)
        self.assertTrue(all("created_at" in row for row in export_all["actions"]))

        filtered = self.db.get_moderation_actions_export(server_id, action_types=["bulk_ban"])
        self.assertEqual(filtered["count"], 1)
        self.assertEqual(filtered["actions"][0]["action_type"], "bulk_ban")
        self.assertEqual(filtered["actions"][0]["target_id"], "user456")

        future_export = self.db.get_moderation_actions_export(
            server_id,
            start=datetime.now() + timedelta(hours=1),
        )
        self.assertEqual(future_export["count"], 0)

    def test_referral_workflow(self):
        self._create_member("alice")
        overview = self.db.get_referral_overview("alice")
        self.assertIsNone(overview["referral"])

        code_info = self.db.ensure_referral_code("alice")
        self.assertIsNotNone(code_info)
        code = code_info["code"]
        self.assertTrue(code)

        # Record multiple hits
        self.db.record_referral_hit(code, landing_page="/landing")
        self.db.record_referral_hit(code, landing_page="/landing")
        self.db.record_referral_hit(code, landing_page="/pricing")
        updated = self.db.get_referral_overview("alice")
        self.assertEqual(updated["metrics"]["total_hits"], 3)

        self._create_member("bob")
        conversion = self.db.redeem_referral_code(code, "bob")
        self.assertEqual(conversion["metrics"]["total_conversions"], 1)

        with self.assertRaises(ValueError):
            self.db.redeem_referral_code(code, "bob")

    def test_server_tips_crud_and_dismissal(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Tip Test Server",
            visibility="public",
        )
        tip = self.db.create_server_tip(
            server["id"],
            "owner",
            "Welcome to the community!",
            "Introduce yourself in #introductions.",
            cta_label="Say hello",
            cta_url="https://example.com/hello",
            priority=5,
        )
        self.assertTrue(tip["active"])

        tips_for_member = self.db.list_server_tips(server["id"], viewer_username="owner")
        self.assertEqual(len(tips_for_member), 1)

        self.db.dismiss_server_tip(tip["id"], "owner")
        remaining = self.db.list_server_tips(server["id"], viewer_username="owner")
        self.assertEqual(len(remaining), 0)

        # Admin can still view when including dismissed
        admin_list = self.db.list_server_tips(
            server["id"],
            viewer_username="owner",
            include_inactive=True,
            include_dismissed=True,
        )
        self.assertEqual(len(admin_list), 1)

        updated_tip = self.db.update_server_tip(server["id"], tip["id"], {"active": False})
        self.assertFalse(updated_tip["active"])

        self.db.delete_server_tip(server["id"], tip["id"])
        after_delete = self.db.list_server_tips(
            server["id"],
            viewer_username="owner",
            include_inactive=True,
            include_dismissed=True,
        )
        self.assertEqual(after_delete, [])

    def test_user_streak_tracking(self):
        self._create_member("streaker")
        starting = self.db.get_user_streak("streaker")
        self.assertEqual(starting["current_streak"], 0)
        self.assertEqual(starting["longest_streak"], 0)

        day_one = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        self.db.record_user_engagement("streaker", "message", event_time=day_one)
        after_day_one = self.db.get_user_streak("streaker")
        self.assertEqual(after_day_one["current_streak"], 1)
        self.assertEqual(after_day_one["longest_streak"], 1)

        day_two = day_one + timedelta(days=1)
        self.db.record_user_engagement("streaker", "message", event_time=day_two)
        after_day_two = self.db.get_user_streak("streaker")
        self.assertEqual(after_day_two["current_streak"], 2)
        self.assertEqual(after_day_two["longest_streak"], 2)

        day_four = day_one + timedelta(days=3)
        self.db.record_user_engagement("streaker", "message", event_time=day_four)
        after_break = self.db.get_user_streak("streaker")
        self.assertEqual(after_break["current_streak"], 1)
        self.assertEqual(after_break["longest_streak"], 2)

    def test_server_boost_tiers_and_boosts(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Boosted Server",
            visibility="public",
        )
        tier = self.db.create_server_boost_tier(
            server["id"],
            name="Level 1",
            price_cents=500,
            description="Basic perks",
            benefits={"slots": 5},
        )
        self.assertTrue(tier["is_active"])

        tiers = self.db.list_server_boost_tiers(server["id"])
        self.assertEqual(len(tiers), 1)

        updated = self.db.update_server_boost_tier(server["id"], tier["id"], {"is_active": False})
        self.assertFalse(updated["is_active"])

        active_again = self.db.update_server_boost_tier(server["id"], tier["id"], {"is_active": True})
        self.assertTrue(active_again["is_active"])

        boost = self.db.activate_server_boost(
            server["id"],
            tier["id"],
            purchaser_username="owner",
            duration_days=7,
        )
        self.assertEqual(boost["status"], self.db.BOOST_STATUS_ACTIVE)

        boosts = self.db.list_server_boosts(server["id"], include_expired=False)
        self.assertEqual(len(boosts), 1)

        cancelled = self.db.cancel_server_boost(server["id"], boost["id"])
        self.assertEqual(cancelled["status"], self.db.BOOST_STATUS_CANCELLED)

        self.db.delete_server_boost_tier(server["id"], tier["id"])
        tiers_after_delete = self.db.list_server_boost_tiers(server["id"], include_inactive=True)
        self.assertEqual(tiers_after_delete, [])

    def test_billing_usage_export(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Billing Server",
            visibility="public",
        )
        tier = self.db.create_server_boost_tier(server["id"], "Gold", 999)
        self.db.activate_server_boost(server["id"], tier["id"], "owner", duration_days=1)

        listing = self.db.save_listing(
            "Premium Item",
            1234,
            "https://example.com/premium",
            premium_placement=1,
            user_id="owner",
        )
        self.db.increment_listing_premium_impression(listing["id"])
        self.db.increment_listing_premium_click(listing["id"])

        start = datetime.now() - timedelta(days=2)
        end = datetime.now() + timedelta(days=1)
        usage = self.db.get_billing_usage(start, end)
        self.assertTrue(any(row["server_slug"] == server["slug"] for row in usage))

    def test_premium_listing_metrics(self):
        listing = self.db.save_listing(
            "Premium Listing",
            2000,
            "https://example.com/listing",
            premium_placement=1,
            user_id="owner",
        )
        self.assertIsNotNone(listing)
        self.db.increment_listing_premium_impression(listing["id"])
        self.db.increment_listing_premium_click(listing["id"])

        analytics = self.db.get_market_insights(days=7)
        self.assertIn("top_keywords", analytics)
        self.assertIn("price_distribution", analytics)

    def test_dm_conversation_rename_and_leave(self):
        self._create_member("owner")
        self._create_member("member1")
        self._create_member("member2")

        conversation = self.db.create_dm_conversation("owner", ["member1", "member2"], title="Initial")
        conv_id = conversation["id"]
        updated = self.db.rename_dm_conversation(conv_id, "owner", "New Title")
        self.assertEqual(updated.get("title"), "New Title")

        with self.assertRaises(ValueError):
            self.db.rename_dm_conversation(conv_id, "member1", "Cannot Rename")

        self.assertTrue(self.db.leave_dm_conversation(conv_id, "member1"))
        member_conversations = self.db.list_dm_conversations("member1")
        self.assertFalse(any(c["id"] == conv_id for c in member_conversations))

        convo_after_leave = self.db.get_dm_conversation(conv_id, "owner")
        self.assertTrue(any(p["username"] == "member1" and p["left_at"] is not None for p in convo_after_leave.get("participants", [])))

        self.assertTrue(self.db.leave_dm_conversation(conv_id, "owner"))
        owner_conversations = self.db.list_dm_conversations("owner")
        self.assertFalse(any(c["id"] == conv_id for c in owner_conversations))

        remaining = self.db.get_dm_conversation(conv_id, "member2")
        self.assertTrue(any((p["username"] == "member2" and (p.get("role") or "").lower() == "owner") for p in remaining.get("participants", [])))

        request, created = self.db.create_friend_request("owner", "member1")
        self.assertTrue(created)
        self.db.respond_friend_request(request["id"], "member1", "accept")

        direct_convo = self.db.ensure_dm_conversation_between("owner", "member1")
        with self.assertRaises(ValueError):
            self.db.leave_dm_conversation(direct_convo["id"], "owner")

    def test_discover_servers_filters_and_meta(self):
        self._create_member("viewer")
        server_primary = self.db.create_server(
            owner_username="owner",
            name="Austin Vintage Finds",
            topic_tags=["vintage", "cars"],
            visibility="public",
            settings={"location": {"city": "Austin", "country": "US"}},
        )
        self._create_member("collector1")
        join_collector1 = self.db.join_server(server_primary["slug"], "collector1")
        self.assertTrue(join_collector1["activated"])
        self._create_member("collector2")
        join_collector2 = self.db.join_server(server_primary["slug"], "collector2")
        self.assertTrue(join_collector2["activated"])
        self._create_member("collector3")
        join_collector3 = self.db.join_server(server_primary["slug"], "collector3")
        self.assertTrue(join_collector3["activated"])

        request_friend, created_friend = self.db.create_friend_request("viewer", "collector1")
        self.assertTrue(created_friend)
        self.db.respond_friend_request(request_friend["id"], "collector1", "accept")

        self.assertTrue(self.db.update_profile("viewer", {
            "search_interests": [{"label": "Vintage"}, {"label": "Auctions"}],
        }))

        server_details = self.db.get_server_by_slug(server_primary["slug"], viewer_username="owner", include_channels=False, include_roles=False)
        self.assertGreaterEqual(server_details.get("member_count", 0), 3)

        self.db.create_server(
            owner_username="owner",
            name="Seattle Gear Traders",
            topic_tags=["gear", "outdoors"],
            visibility="public",
            settings={"location": "Seattle, US"},
        )

        discovery = self.db.discover_servers(
            viewer_username="viewer",
            query="Austin",
            tags=["Vintage"],
            limit=10,
            offset=0,
            location="Austin",
            min_members=2,
        )
        meta = discovery.get("meta") or {}
        results = discovery.get("results") or []
        self.assertGreaterEqual(meta.get("total", 0), 1)
        self.assertTrue(results)
        primary = results[0]
        self.assertEqual(primary["slug"], server_primary["slug"])
        self.assertGreaterEqual(primary.get("member_count", 0), 3)
        self.assertIn("discovery_score", primary)
        self.assertEqual(meta.get("order"), "popularity")
        personalization = primary.get("personalization") or {}
        self.assertGreaterEqual(personalization.get("friend_member_count", 0), 1)
        self.assertGreaterEqual(personalization.get("interest_overlap", 0), 1)

        trending = discovery.get("trending") or []
        for server in trending:
            self.assertIn("discovery_score", server)

    def test_home_feed_prioritizes_user_events(self):
        self._create_member("alice")
        self._create_member("bob")
        server = self.db.create_server(
            owner_username="alice",
            name="Feed Hub",
            topic_tags=["community"],
            visibility="public",
            settings={"location": "Chicago, US"},
        )
        self.db.join_server(server["slug"], "bob")

        old_time = datetime.now() - timedelta(hours=48)
        self.db.log_feed_event(
            "listing_alert",
            actor_username="alice",
            audience_type="global",
            payload={"title": "Vintage chair listed", "url": "/listings/1"},
            created_at=old_time,
        )
        self.db.log_feed_event(
            "server_announcement",
            actor_username="alice",
            server_slug=server["slug"],
            audience_type="server",
            payload={"title": "Weekly meetup announced", "server_name": server["name"]},
        )
        self.db.log_feed_event(
            "dm_message",
            actor_username="alice",
            target_username="bob",
            audience_type="user",
            payload={
                "sender_display": "Alice",
                "preview": "Hey! Are you coming to the meetup?",
                "url": "/messages",
            },
        )

        self._create_member("owner2")
        gaming_server = self.db.create_server(
            owner_username="owner2",
            name="Gaming Den",
            topic_tags=["gaming"],
            visibility="public",
        )
        self.assertTrue(self.db.update_profile("bob", {
            "search_interests": [{"label": "Gaming"}],
        }))

        feed = self.db.get_home_feed("bob", limit=10, offset=0)
        events = feed.get("events") or []
        self.assertTrue(events)
        meta_total = feed["meta"].get("total", 0)
        appended = feed["meta"].get("recommended_appended", 0)
        self.assertGreaterEqual(meta_total + appended, len(events))
        self.assertEqual(events[0]["event_type"], "dm_message")
        self.assertIn("summary", events[0])
        self.assertIn("title", events[0]["summary"])
        self.assertGreater(events[0]["computed_score"], events[-1]["computed_score"])

        server_feed = self.db.get_server_feed(server["slug"], limit=10, offset=0)
        self.assertGreaterEqual(server_feed["meta"].get("total", 0), len(server_feed.get("events", [])))
        self.assertIn("summary", server_feed["events"][0])
        self.assertIn("title", server_feed["events"][0]["summary"])

        recommendation_types = {event["event_type"] for event in feed.get("events", [])}
        self.assertIn("server_recommendation", recommendation_types)

        recommendation_types = {event["event_type"] for event in feed.get("events", [])}
        self.assertIn("server_recommendation", recommendation_types)

    def test_profile_identity_fields_visibility(self):
        self._create_member("owner")
        self.db.ensure_profile("owner")
        self.assertTrue(self.db.update_profile("owner", {
            "pronouns": "they/them",
            "gender": "Non-binary",
        }))
        profile = self.db.get_profile("owner")
        self.assertEqual(profile["pronouns"], "they/them")
        self.assertEqual(profile["gender"], "Non-binary")

        visibility = self.db.update_profile_visibility("owner", {
            "pronouns": "connections",
            "gender": "private",
        })
        self.assertEqual(visibility["pronouns"], "connections")
        self.assertEqual(visibility["gender"], "private")

        viewer_profile = self.db.get_profile_for_viewer("owner", viewer_username="viewer1")
        self.assertEqual(viewer_profile["pronouns"], "they/them")
        self.assertIsNone(viewer_profile["gender"])

        anon_profile = self.db.get_profile_for_viewer("owner", viewer_username=None)
        self.assertIsNone(anon_profile["pronouns"])

    def test_support_ticket_lifecycle(self):
        self._create_member("admin_user")
        self.db.update_user_role("admin_user", "admin")

        server = self.db.create_server(
            owner_username="owner",
            name="Support HQ",
            topic_tags=["moderation"],
            visibility="public",
        )

        ticket = self.db.create_support_ticket(
            reporter_username="owner",
            subject="Need moderation assistance",
            body="User is spamming links in the general channel.",
            server_id=server["id"],
            severity="high",
        )
        self.assertEqual(ticket["status"], "open")
        self.assertEqual(ticket["severity"], "high")
        self.assertIsNone(ticket["first_response_at"])

        event = self.db.add_support_ticket_event(
            ticket["id"],
            "admin_user",
            "comment",
            comment="Acknowledged. Reviewing logs now.",
        )
        self.assertEqual(event["event_type"], "comment")

        ticket_after_comment = self.db.get_support_ticket(ticket["id"], "admin_user")
        self.assertIsNotNone(ticket_after_comment["first_response_at"])

        updated_ticket = self.db.update_support_ticket(
            ticket["id"],
            "admin_user",
            status="in_progress",
            assigned_to="admin_user",
        )
        self.assertEqual(updated_ticket["status"], "in_progress")
        self.assertEqual(updated_ticket["assigned_to"], "admin_user")

        resolved_ticket = self.db.update_support_ticket(
            ticket["id"],
            "admin_user",
            status="resolved",
            comment="User removed and messages cleaned.",
        )
        self.assertEqual(resolved_ticket["status"], "resolved")
        self.assertIsNotNone(resolved_ticket["resolved_at"])

        events = self.db.list_support_ticket_events(ticket["id"], "admin_user")
        self.assertGreaterEqual(len(events), 3)

        reporter_view = self.db.get_support_ticket(ticket["id"], "owner")
        self.assertEqual(reporter_view["status"], "resolved")

        listing = self.db.list_support_tickets("admin_user", status="resolved")
        self.assertGreaterEqual(listing["total"], 1)
        self.assertIn(ticket["id"], {entry["id"] for entry in listing["tickets"]})

    def test_support_metrics_summary(self):
        self._create_member("admin_user")
        self.db.update_user_role("admin_user", "admin")

        server = self.db.create_server(
            owner_username="owner",
            name="Metrics Guild",
            topic_tags=["metrics"],
            visibility="public",
        )

        open_ticket = self.db.create_support_ticket(
            reporter_username="owner",
            subject="Open question",
            body="Need help understanding permissions.",
            server_id=server["id"],
            severity="high",
        )

        resolved_ticket = self.db.create_support_ticket(
            reporter_username="owner",
            subject="Resolved incident",
            body="Initial outage resolved after redeploy.",
            server_id=server["id"],
            severity="medium",
        )

        now = datetime.now()
        with self.db.get_pool().get_connection() as conn:
            c = conn.cursor()
            open_created = now - timedelta(hours=18)
            c.execute("""
                UPDATE support_tickets
                SET created_at = ?, updated_at = ?, last_activity_at = ?, severity = 'high'
                WHERE id = ?
            """, (open_created, open_created, open_created, open_ticket["id"]))

            resolved_created = now - timedelta(hours=30)
            first_response = resolved_created + timedelta(hours=1)
            resolved_at = resolved_created + timedelta(hours=6)
            c.execute("""
                UPDATE support_tickets
                SET created_at = ?, first_response_at = ?, resolved_at = ?, updated_at = ?, last_activity_at = ?, status = 'resolved', severity = 'medium', assigned_to = 'admin_user'
                WHERE id = ?
            """, (resolved_created, first_response, resolved_at, resolved_at, resolved_at, resolved_ticket["id"]))
            conn.commit()

        metrics = self.db.get_support_metrics(window_hours=48)
        self.assertEqual(metrics["tickets_considered"], 2)
        self.assertEqual(metrics["open_count"], 1)
        self.assertIn("high", metrics["open_by_severity"])
        self.assertGreaterEqual(metrics["response_sla_breach_count"], 1)
        self.assertAlmostEqual(metrics["avg_first_response_hours"], 1.0, places=2)
        self.assertAlmostEqual(metrics["avg_resolution_hours"], 6.0, places=2)

        admin_metrics = self.db.get_support_metrics(window_hours=48, assigned_to="admin_user")
        self.assertEqual(admin_metrics["tickets_considered"], 1)
        self.assertEqual(admin_metrics["open_count"], 0)
        self.assertEqual(admin_metrics["response_sla_breach_count"], 0)

    def test_user_data_export_and_purge(self):
        self.db.create_user_db("owner", "owner@example.com", "hash")
        self.db.ensure_profile("owner")
        server = self.db.create_server(
            owner_username="owner",
            name="Export Playground",
            topic_tags=["export"],
            visibility="public",
        )
        self.db.create_support_ticket(
            reporter_username="owner",
            subject="Export test",
            body="Testing export functionality.",
            server_id=server["id"],
        )
        export_payload = self.db.export_user_data("owner")
        self.assertEqual(export_payload["username"], "owner")
        self.assertIn("user", export_payload)
        self.assertIn("profile", export_payload)
        self.assertGreaterEqual(len(export_payload.get("support_tickets", [])), 1)

        self.db.purge_user_data("owner")
        with self.assertRaises(ValueError):
            self.db.export_user_data("owner")

    def test_friend_overview_mutuals(self):
        self._create_member("owner")
        self._create_member("friend")
        self._create_member("mutual")

        request, created = self.db.create_friend_request("owner", "friend")
        self.assertTrue(created)
        self.db.respond_friend_request(request["id"], "friend", "accept")

        request_mutual, created_mutual = self.db.create_friend_request("owner", "mutual")
        self.assertTrue(created_mutual)
        self.db.respond_friend_request(request_mutual["id"], "mutual", "accept")

        bridge_request, bridge_created = self.db.create_friend_request("mutual", "friend")
        self.assertTrue(bridge_created)
        self.db.respond_friend_request(bridge_request["id"], "friend", "accept")

        shared_server = self.db.create_server(
            owner_username="owner",
            name="Shared Hub",
            topic_tags=["community"],
            visibility="public",
        )
        self.db.join_server(shared_server["slug"], "friend")

        overview = self.db.get_friend_overview("owner", limit=10)
        friend_entry = next(item for item in overview["friends"] if item["username"] == "friend")
        self.assertEqual(friend_entry["mutual_friend_count"], 1)
        self.assertEqual(friend_entry["mutual_friend_preview"][0]["username"], "mutual")
        self.assertEqual(friend_entry["mutual_server_count"], 1)
        self.assertEqual(friend_entry["mutual_server_preview"][0]["slug"], shared_server["slug"])

        self._create_member("newbie")
        step_request, step_created = self.db.create_friend_request("newbie", "mutual")
        self.assertTrue(step_created)
        self.db.respond_friend_request(step_request["id"], "mutual", "accept")
        incoming_request, incoming_created = self.db.create_friend_request("newbie", "owner")
        self.assertTrue(incoming_created)

        incoming = self.db.list_friend_requests("owner", direction="incoming")
        incoming_entry = next(item for item in incoming if item["id"] == incoming_request["id"])
        self.assertEqual(incoming_entry["mutual_friend_count"], 1)

    def test_server_analytics_summary(self):
        server = self.db.create_server(
            owner_username="owner",
            name="Analytics Hub",
            topic_tags=["analytics", "community"],
            visibility="public",
        )
        channels = self.db.get_server_channels(server["id"])
        general = channels[0]
        self.db.create_channel_message(general["id"], "owner", "Welcome analytics!")
        self._create_member("analyst")
        self.db.join_server(server["slug"], "analyst")
        analytics = self.db.get_server_analytics(server["id"], days=30)
        self.assertEqual(analytics["server"]["id"], server["id"])
        self.assertGreaterEqual(analytics["members"]["total"], 1)
        self.assertIn("messages", analytics)
        self.assertIn("channels", analytics)
        self.assertIn("reports", analytics)
        self.assertIn("generated_at", analytics)

    def test_server_owner_digest_pipeline(self):
        self._create_member("owner")
        self._create_member("member1")
        self._create_member("member2")

        server = self.db.create_server(
            owner_username="owner",
            name="Digest Hub",
            topic_tags=["community"],
            visibility="public",
        )
        channels = self.db.get_server_channels(server["id"])
        general = channels[0]

        self.db.join_server(server["slug"], "member1")
        self.db.join_server(server["slug"], "member2")

        self.db.create_channel_message(general["id"], "member1", "Hello team!")
        self.db.create_channel_message(general["id"], "member1", "Follow-up note")
        self.db.create_channel_message(general["id"], "member2", "Glad to be here")

        self.db.create_report(
            "member1",
            "server",
            server["slug"],
            context={
                "server_slug": server["slug"],
                "reason": "Test moderation alert",
            },
        )

        digest_preview = self.db.compute_server_owner_digest(server["id"], "owner", period_days=7)
        self.assertEqual(digest_preview["owner_username"], "owner")
        self.assertGreaterEqual(digest_preview["metrics"]["members"]["new_count"], 2)
        self.assertGreater(digest_preview["metrics"]["messages"]["total"], 0)

        queued_digest = self.db.enqueue_server_owner_digest(server["id"], "owner", period_days=7)
        self.assertEqual(queued_digest["status"], "pending")

        pending = self.db.get_pending_owner_digests(limit=5)
        pending_ids = {item["id"] for item in pending}
        self.assertIn(queued_digest["id"], pending_ids)

        delivered = self.db.mark_server_owner_digest_delivered(queued_digest["id"])
        self.assertEqual(delivered["status"], "delivered")

        history = self.db.list_server_owner_digests(server["id"], limit=5)
        self.assertTrue(any(item["id"] == queued_digest["id"] for item in history))

    def test_community_analytics_overview(self):
        self._create_member("maker")
        maker_server = self.db.create_server(
            owner_username="maker",
            name="Makerspace",
            topic_tags=["maker", "tools"],
            visibility="public",
        )
        channels = self.db.get_server_channels(maker_server["id"])
        self.db.create_channel_message(channels[0]["id"], "maker", "First post")
        analytics = self.db.get_community_analytics(days=30)
        self.assertGreaterEqual(analytics["servers"]["total"], 1)
        self.assertIn("top_topics", analytics)
        self.assertIn("reports", analytics)
        self.assertIn("generated_at", analytics)

if __name__ == "__main__":
    unittest.main()

