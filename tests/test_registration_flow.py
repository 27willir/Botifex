import re
import uuid

import db_enhanced
from app import app


def _extract_csrf_token(html: str) -> str:
    """Pull the CSRF token value out of the registration form."""
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "CSRF token not found in registration form"
    return match.group(1)


def test_registration_allows_new_user():
    """Ensure the /register endpoint succeeds with valid input."""
    db_enhanced.reset_rate_limit("127.0.0.1", "register")

    unique_suffix = uuid.uuid4().hex[:8]
    username = f"regtest_{unique_suffix}"
    email = f"{username}@example.com"

    with app.test_client() as client:
        response = client.get("/register")
        assert response.status_code == 200

        token = _extract_csrf_token(response.data.decode("utf-8"))

        post_response = client.post(
            "/register",
            data={
                "username": username,
                "password": "ValidPass1!",
                "email": email,
                "agree_terms": "on",
                "csrf_token": token,
            },
            follow_redirects=False,
        )

        assert post_response.status_code == 302
        assert post_response.headers.get("Location", "").endswith("/login")

    db_enhanced.reset_rate_limit("127.0.0.1", "register")

