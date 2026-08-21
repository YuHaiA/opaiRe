import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import global_state


class AuthTokenTests(unittest.TestCase):
    def setUp(self):
        self.secret_patch = patch.object(
            global_state, "_auth_secret_bytes", return_value=b"test-auth-secret" * 4
        )
        self.secret_patch.start()

    def tearDown(self):
        self.secret_patch.stop()

    def test_signed_token_survives_memory_reset(self):
        with patch.object(global_state.cfg, "WEB_PASSWORD", "test-password"):
            token = global_state.create_auth_token()
            global_state.VALID_TOKENS.discard(token)

            self.assertTrue(global_state.is_valid_auth_token(token))
            self.assertEqual(
                token,
                asyncio.run(global_state.verify_token(f"Bearer {token}")),
            )

    def test_tampered_token_is_rejected(self):
        with patch.object(global_state.cfg, "WEB_PASSWORD", "test-password"):
            token = global_state.create_auth_token()
            self.assertFalse(global_state.is_valid_auth_token(token + "x"))

    def test_password_change_invalidates_token(self):
        with patch.object(global_state.cfg, "WEB_PASSWORD", "old-password"):
            token = global_state.create_auth_token()
        with patch.object(global_state.cfg, "WEB_PASSWORD", "new-password"):
            self.assertFalse(global_state.is_valid_auth_token(token))

    def test_expired_token_is_rejected(self):
        issued_at = 1_000_000
        with patch.object(global_state.cfg, "WEB_PASSWORD", "test-password"), \
             patch.object(global_state.time, "time", return_value=issued_at):
            token = global_state.create_auth_token()
        with patch.object(global_state.cfg, "WEB_PASSWORD", "test-password"), \
             patch.object(
                 global_state.time,
                 "time",
                 return_value=issued_at + global_state.AUTH_TOKEN_TTL_SECONDS + 1,
             ):
            self.assertFalse(global_state.is_valid_auth_token(token))

    def test_legacy_memory_token_still_works(self):
        token = "legacy-test-token"
        global_state.VALID_TOKENS.add(token)
        try:
            self.assertTrue(global_state.is_valid_auth_token(token))
        finally:
            global_state.VALID_TOKENS.discard(token)

    def test_missing_bearer_token_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(global_state.verify_token(None))
        self.assertEqual(401, raised.exception.status_code)


if __name__ == "__main__":
    unittest.main()
