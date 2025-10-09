# test_password.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import check_password_hash
import getpass

# replace with the hash you want to test, or leave blank to prompt for it
hash_from_file = input("Paste the hash to test (or press Enter to read from users.json): ").strip()

if not hash_from_file:
    import json
    USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "users.json")
    if not os.path.exists(USERS_FILE):
        print("users.json not found.")
        raise SystemExit(1)
    with open(USERS_FILE, "r") as f:
        data = f.read().strip()
        users = json.loads(data) if data else []
        if not users:
            print("No users found in users.json.")
            raise SystemExit(1)
        # default to first user's hash
        hash_from_file = users[0].get("password")
        print(f"Using hash from users.json for user: {users[0].get('username')}")

password = getpass.getpass("Enter plaintext password to test: ")

if check_password_hash(hash_from_file, password):
    print("✅ Password is correct for that hash.")
else:
    print("❌ Password does NOT match that hash.")
