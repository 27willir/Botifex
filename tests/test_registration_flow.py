import re
import uuid
from unittest import mock

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

    pending = db_enhanced.create_pending_signup(email=email, plan_tier="pro")
    db_enhanced.mark_pending_signup_paid(
        pending["id"],
        stripe_customer_id=None,
        stripe_subscription_id=None,
        plan_tier="pro",
        payment_status="paid",
    )

    with app.test_client() as client:
        response = client.get(f"/register?pending={pending['id']}")
        assert response.status_code == 200

        register_csrf = _extract_csrf_token(response.data.decode("utf-8"))

        with mock.patch("app.is_email_configured", return_value=True), \
             mock.patch("app.send_verification_email") as send_email_mock, \
             mock.patch("app.send_welcome_email", return_value=True):
            post_response = client.post(
                "/register",
                data={
                    "pending_id": pending["id"],
                    "first_name": "Test",
                    "last_name": "User",
                    "phone": "+12085551212",
                    "zip_code": "83702",
                    "username": username,
                    "password": "ValidPass1!",
                    "password_confirm": "ValidPass1!",
                    "email": email,
                    "agree_terms": "on",
                    "csrf_token": register_csrf,
                },
                follow_redirects=False,
            )

        assert post_response.status_code == 302
        assert post_response.headers.get("Location", "").endswith("/verify-email-code")

        send_email_mock.assert_called_once()
        verification_code = send_email_mock.call_args.kwargs.get("verification_code")
        assert verification_code, "Verification code should be included in the email payload"

        entry = db_enhanced.get_latest_verification_entry(username)
        assert entry is not None
        assert entry["code_hash"], "Verification code hash should be stored"
        assert not entry["used"]

        verify_page = client.get("/verify-email-code")
        assert verify_page.status_code == 200
        verify_csrf = _extract_csrf_token(verify_page.data.decode("utf-8"))

        verify_response = client.post(
            "/verify-email-code",
            data={
                "username": username,
                "verification_code": verification_code,
                "csrf_token": verify_csrf,
            },
            follow_redirects=False,
        )

        assert verify_response.status_code == 302
        assert verify_response.headers.get("Location", "").endswith("/login")

        user_record = db_enhanced.get_user_by_username(username)
        assert user_record is not None
        assert user_record.get("verified") is True

        pending_record = db_enhanced.get_pending_signup(pending["id"])
        assert pending_record is not None
        assert pending_record["status"] == "completed"

    db_enhanced.reset_rate_limit("127.0.0.1", "register")

