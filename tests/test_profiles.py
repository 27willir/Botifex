import os
import sys
import shutil
import tempfile
import importlib
import unittest
from datetime import date, datetime, timedelta


class ProfileDBTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.mkdtemp(prefix="profiles_test_")
        cls.db_path = os.path.join(cls._temp_dir, "profiles.db")
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
        self.db.create_user_db("alice", "alice@example.com", "hash")
        self.db.ensure_profile("alice")

    def tearDown(self):
        self.db.close_database()
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_profile_defaults(self):
        profile = self.db.get_profile("alice")
        self.assertEqual(profile["display_name"], "alice")
        self.assertEqual(profile["search_interests"], [])
        visibility = profile["visibility_settings"]
        self.assertEqual(visibility.get("display_name"), "public")
        self.assertEqual(visibility.get("avatar_url"), "public")
        self.assertEqual(visibility.get("bio"), "connections")

    def test_update_profile_fields(self):
        updates = {
            "display_name": "Alice Motors",
            "bio": "Collector of classic muscle cars.",
            "location": "Boise, ID",
            "search_interests": [
                {"id": "firebird", "label": "Pontiac Firebird", "category": "automotive"},
                {"label": "Vintage wheels", "category": "collectibles"},
            ],
        }
        self.db.update_profile("alice", updates)
        profile = self.db.get_profile("alice")
        self.assertEqual(profile["display_name"], "Alice Motors")
        self.assertEqual(profile["bio"], "Collector of classic muscle cars.")
        self.assertEqual(profile["location"], "Boise, ID")
        interests = profile["search_interests"]
        self.assertEqual(len(interests), 2)
        labels = {interest["label"] for interest in interests}
        self.assertIn("Pontiac Firebird", labels)
        self.assertIn("Vintage wheels", labels)

    def test_visibility_filtering(self):
        self.db.update_profile("alice", {"bio": "Private bio text"})
        self.db.update_profile_visibility("alice", {"bio": "private"})
        public_view = self.db.get_profile_for_viewer("alice", None)
        self.assertIsNone(public_view["bio"])
        self.db.update_profile_visibility("alice", {"bio": "connections"})
        self.db.create_user_db("bob", "bob@example.com", "hash")
        self.db.ensure_profile("bob")
        connections_view = self.db.get_profile_for_viewer("alice", "bob")
        self.assertEqual(connections_view["bio"], "Private bio text")

    def test_showcase_management(self):
        search_id = self.db.create_saved_search("alice", "Garage Finds", keywords="garage", notify_new=False)
        listing_id = self.db.save_listing("Rare Camaro", 25000, "https://example.com/camaro", source="test")
        self.db.add_favorite("alice", listing_id)

        self.db.set_profile_showcase(
            "alice",
            "favorite_searches",
            [{"entity_id": str(search_id), "label": "Garage Finds", "note": "Weekly sweep"}],
        )
        self.db.set_profile_showcase(
            "alice",
            "servers_joined",
            [{"entity_id": "classic-cars-hub", "label": "Classic Cars Hub", "note": "Great trading tips"}],
        )

        showcase = self.db.get_profile_showcase("alice")
        self.assertEqual(len(showcase["favorite_searches"]), 1)
        self.assertEqual(showcase["favorite_searches"][0]["entity_id"], str(search_id))
        self.assertEqual(showcase["favorite_searches"][0]["metadata"].get("note"), "Weekly sweep")
        self.assertEqual(len(showcase["servers_joined"]), 1)
        self.assertEqual(showcase["servers_joined"][0]["label"], "Classic Cars Hub")

    def test_profile_activity_visibility(self):
        self.db.log_profile_activity(
            "alice",
            "profile_updated",
            metadata={"fields": ["bio"], "note": "Updated profile bio"},
            visibility="connections",
        )
        public_activity = self.db.get_profile_activity("alice", viewer_username=None)
        self.assertEqual(public_activity, [])

        self.db.update_profile_visibility("alice", {"recent_activity": "public"})
        self.db.log_profile_activity(
            "alice",
            "profile_updated",
            metadata={"fields": ["bio"], "note": "Now public"},
            visibility="public",
        )
        public_activity = self.db.get_profile_activity("alice", viewer_username=None)
        self.assertEqual(len(public_activity), 1)
        self.assertEqual(public_activity[0]["metadata"]["fields"], ["bio"])

    def test_add_profile_contact_creates_dm(self):
        self.db.create_user_db("bob", "bob@example.com", "hash")
        self.db.ensure_profile("bob")

        contact, created = self.db.add_profile_contact("alice", "bob")
        self.assertTrue(created)
        self.assertEqual(contact["contact_username"], "bob")
        self.assertTrue(self.db.is_profile_contact("alice", "bob"))

        # Idempotent insert
        _, created_again = self.db.add_profile_contact("alice", "bob")
        self.assertFalse(created_again)

        request, created_request = self.db.create_friend_request("alice", "bob")
        self.assertTrue(created_request)
        self.db.respond_friend_request(request["id"], "bob", "accept")

        conversation = self.db.ensure_dm_conversation_between("alice", "bob")
        self.assertIsNotNone(conversation)
        participant_usernames = {p["username"] for p in conversation["participants"]}
        self.assertEqual(participant_usernames, {"alice", "bob"})

    def test_friend_code_flow(self):
        code_info = self.db.ensure_friend_code("alice")
        self.assertTrue(code_info.get("code"))

        self.db.create_user_db("bob", "bob@example.com", "hash")
        self.db.ensure_profile("bob")

        result = self.db.redeem_friend_code(code_info["code"], "bob")
        self.assertEqual(result["owner_username"], "alice")
        self.assertTrue(result["created"])
        request = result["request"]
        self.assertEqual(request["requester_username"], "bob")
        self.assertEqual(request["recipient_username"], "alice")

        repeat = self.db.redeem_friend_code(code_info["code"], "bob")
        self.assertFalse(repeat["created"])
        self.assertEqual(repeat["request"]["id"], request["id"])

        updated = self.db.respond_friend_request(request["id"], "alice", "accept")
        self.assertEqual(updated["status"], self.db.FRIEND_REQUEST_STATUS_ACCEPTED)
        self.assertTrue(self.db.are_friends("alice", "bob"))
        conversation = self.db.ensure_dm_conversation_between("alice", "bob")
        self.assertIsNotNone(conversation)


class StreakDateParsingTestCase(unittest.TestCase):
    def test_record_user_engagement_handles_native_date(self):
        import db_enhanced as db

        previous_day = date.today() - timedelta(days=1)

        class FakeCursor:
            def __init__(self):
                self.mode = None
                self.insert_params = None

            def execute(self, query, params=()):
                normalized = query.strip().lower()
                if normalized.startswith("select"):
                    self.mode = "select"
                elif "insert into user_streaks" in normalized:
                    self.mode = "insert"
                    self.insert_params = params
                else:
                    self.mode = None

                self.last_query = query
                self.last_params = params

            def fetchone(self):
                if self.mode == "select":
                    return ("alice", 3, 5, previous_day)
                return None

        class FakeConnection:
            def __init__(self):
                self.cursor_obj = FakeCursor()
                self.committed = False

            def cursor(self):
                return self.cursor_obj

            def commit(self):
                self.committed = True

        class FakeConnectionContext:
            def __init__(self, conn):
                self.conn = conn

            def __enter__(self):
                return self.conn

            def __exit__(self, exc_type, exc, tb):
                return False

        class FakePool:
            def __init__(self, conn):
                self.conn = conn

            def get_connection(self):
                return FakeConnectionContext(self.conn)

        fake_conn = FakeConnection()
        fake_pool = FakePool(fake_conn)
        original_pool = db._connection_pool
        try:
            db._connection_pool = fake_pool
            event_time = datetime.combine(date.today(), datetime.min.time())
            result = db.record_user_engagement("alice", "message", event_time=event_time)
        finally:
            db._connection_pool = original_pool

        cursor = fake_conn.cursor_obj
        self.assertIsNotNone(cursor.insert_params)
        self.assertEqual(cursor.insert_params[1], 4)  # current_streak
        self.assertEqual(cursor.insert_params[2], 5)  # longest_streak remains max
        self.assertEqual(cursor.insert_params[3], date.today())
        self.assertTrue(fake_conn.committed)

        self.assertEqual(result["current_streak"], 4)
        self.assertEqual(result["longest_streak"], 5)
        self.assertEqual(result["last_engaged_date"], date.today().isoformat())


if __name__ == "__main__":
    unittest.main()

