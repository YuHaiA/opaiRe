import unittest

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


if __name__ == "__main__":
    unittest.main()
