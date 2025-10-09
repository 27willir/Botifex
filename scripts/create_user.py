# create_user.py
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from werkzeug.security import generate_password_hash

USERS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "users.json")

def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    try:
        with open(USERS_FILE, "r") as f:
            data = f.read().strip()
            return json.loads(data) if data else []
    except Exception:
        return []

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=2)

def user_exists(users, username, email):
    for u in users:
        if u.get("username") == username or (email and u.get("email") == email):
            return True
    return False

def create_user(username, plaintext_password, email=None):
    users = load_users()
    if user_exists(users, username, email):
        print(f"User with username '{username}' or email '{email}' already exists.")
        return False
    hashed = generate_password_hash(plaintext_password)
    user = {"username": username, "email": email or "", "password": hashed}
    users.append(user)
    save_users(users)
    print(f"Created user '{username}' with hashed password (stored in {USERS_FILE}).")
    return True

if __name__ == "__main__":
    # Usage: python create_user.py username password [email]
    if len(sys.argv) < 3:
        print("Usage: python create_user.py <username> <password> [email]")
        sys.exit(1)
    username = sys.argv[1]
    password = sys.argv[2]
    email = sys.argv[3] if len(sys.argv) >= 4 else ""
    create_user(username, password, email)
