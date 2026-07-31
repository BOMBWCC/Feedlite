import os
import unittest
from unittest.mock import patch

import jwt
from fastapi import HTTPException
from starlette.requests import Request


class SecurityConfigTestCase(unittest.TestCase):
    def test_rejects_repository_known_password_without_echoing_it(self):
        from app.security_config import validate_security_config

        public_password = "change-this-password"
        environment = {
            "ADMIN_PASSWORD": public_password,
            "JWT_SECRET": "j" * 64,
            "RAG_API_KEY": "",
        }

        with self.assertRaises(ValueError) as raised:
            validate_security_config(environment)

        self.assertIn("ADMIN_PASSWORD", str(raised.exception))
        self.assertNotIn(public_password, str(raised.exception))

    def test_rejects_missing_and_short_required_secrets(self):
        from app.security_config import validate_security_config

        invalid_environments = [
            {"ADMIN_PASSWORD": "", "JWT_SECRET": "j" * 64},
            {"ADMIN_PASSWORD": "long-enough-password", "JWT_SECRET": "short"},
        ]

        for environment in invalid_environments:
            with self.subTest(environment_keys=sorted(environment)):
                with self.assertRaises(ValueError):
                    validate_security_config(environment)

    def test_accepts_strong_secrets_with_rag_disabled(self):
        from app.security_config import validate_security_config

        validate_security_config(
            {
                "ADMIN_PASSWORD": "correct-horse-battery-staple-2026",
                "JWT_SECRET": "a" * 64,
                "RAG_API_KEY": "",
            }
        )

    def test_rejects_public_or_short_optional_rag_key(self):
        from app.security_config import validate_security_config

        for rag_key in ("replace-with-private-rag-api-key", "too-short"):
            with self.subTest(rag_key=rag_key):
                with self.assertRaisesRegex(ValueError, "RAG_API_KEY"):
                    validate_security_config(
                        {
                            "ADMIN_PASSWORD": "correct-horse-battery-staple-2026",
                            "JWT_SECRET": "a" * 64,
                            "RAG_API_KEY": rag_key,
                        }
                    )

    def test_configured_secret_has_no_repository_fallback(self):
        from app.security_config import configured_secret

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "JWT_SECRET"):
                configured_secret("JWT_SECRET")

    def test_constant_time_helper_compares_utf8_values_exactly(self):
        from app.security_config import credentials_match

        self.assertTrue(credentials_match("安全-secret", "安全-secret"))
        self.assertFalse(credentials_match("安全-secret", "different-value"))


class LoginThrottleTestCase(unittest.TestCase):
    def test_blocks_after_five_failures_until_window_expires(self):
        from app.login_throttle import LoginThrottle

        throttle = LoginThrottle(max_failures=5, window_seconds=300)
        for _ in range(5):
            throttle.record_failure("203.0.113.7", now=100.0)

        self.assertTrue(throttle.is_blocked("203.0.113.7", now=399.0))
        self.assertFalse(throttle.is_blocked("203.0.113.7", now=401.0))

    def test_success_clears_failure_state(self):
        from app.login_throttle import LoginThrottle

        throttle = LoginThrottle(max_failures=5, window_seconds=300)
        throttle.record_failure("203.0.113.7", now=100.0)
        throttle.record_success("203.0.113.7")

        self.assertFalse(throttle.is_blocked("203.0.113.7", now=101.0))

    def test_entry_map_is_bounded(self):
        from app.login_throttle import LoginThrottle

        throttle = LoginThrottle(max_failures=5, window_seconds=300, max_entries=2)
        for _ in range(5):
            throttle.record_failure("203.0.113.1", now=100.0)
        self.assertTrue(throttle.is_blocked("203.0.113.1", now=101.0))

        throttle.record_failure("203.0.113.2", now=100.0)
        throttle.record_failure("203.0.113.3", now=100.0)

        self.assertFalse(throttle.is_blocked("203.0.113.1", now=101.0))


class AuthenticationBehaviorTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_login_does_not_fall_back_to_admin_admin(self):
        from app.routers.auth import LoginRequest, login

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "ADMIN_PASSWORD"):
                await login(LoginRequest(username="admin", password="admin"))

    async def test_verifier_does_not_accept_token_without_configured_secret(self):
        from app.auth_deps import verify_token

        public_fallback = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
        forged_token = jwt.encode({"sub": "attacker"}, public_fallback, algorithm="HS256")
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/articles/",
                "headers": [(b"authorization", f"Bearer {forged_token}".encode())],
            }
        )

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "JWT_SECRET"):
                await verify_token(request)

    async def test_login_route_blocks_even_correct_password_after_failure_limit(self):
        from app.login_throttle import LoginThrottle
        from app.routers.auth import LoginRequest, login

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/auth/login",
                "headers": [],
                "client": ("203.0.113.7", 54321),
            }
        )
        environment = {
            "ADMIN_USERNAME": "admin",
            "ADMIN_PASSWORD": "correct-horse-battery-staple-2026",
            "JWT_SECRET": "a" * 64,
        }
        throttle = LoginThrottle(max_failures=2, window_seconds=300)

        with patch.dict(os.environ, environment, clear=True), patch(
            "app.routers.auth.login_throttle",
            throttle,
        ):
            for _ in range(2):
                with self.assertRaises(HTTPException) as failed:
                    await login(
                        LoginRequest(username="admin", password="wrong-password"),
                        request=request,
                    )
                self.assertEqual(failed.exception.status_code, 401)

            with self.assertRaises(HTTPException) as blocked:
                await login(
                    LoginRequest(
                        username="admin",
                        password="correct-horse-battery-staple-2026",
                    ),
                    request=request,
                )

        self.assertEqual(blocked.exception.status_code, 429)


if __name__ == "__main__":
    unittest.main()
