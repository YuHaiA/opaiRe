import unittest
from pathlib import Path

import httpx

from routers import service_routes


class CloudflareRequestRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_transient_disconnects(self):
        expected = object()

        class _FakeClient:
            def __init__(self):
                self.calls = 0

            async def request(self, method, url, **kwargs):
                self.calls += 1
                if self.calls < 3:
                    raise httpx.RemoteProtocolError("Server disconnected without sending a response")
                return expected

        client = _FakeClient()
        result = await service_routes._cloudflare_request_with_retry(
            client,
            "GET",
            "https://api.cloudflare.com/client/v4/zones",
        )

        self.assertIs(expected, result)
        self.assertEqual(3, client.calls)

    def test_bundled_email_worker_contract(self):
        source = service_routes._load_cf_email_worker_source()

        self.assertIn("async email", source)
        self.assertIn('"X-Webhook-Secret"', source)
        self.assertIn("message.raw", source)
        self.assertIn("message.to", source)
        self.assertNotIn("raw.githubusercontent.com", source)

        self.assertEqual(
            Path(service_routes.CF_EMAIL_WORKER_PATH).name,
            "cloudflare-email-worker.js",
        )


if __name__ == "__main__":
    unittest.main()
