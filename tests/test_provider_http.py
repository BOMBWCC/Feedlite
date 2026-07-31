import asyncio
import json
import time
import unittest


class FakeProviderResponse:
    def __init__(self, *, status_code=200, payload=None, chunks=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        encoded = json.dumps(self._payload).encode()
        self._chunks = list(chunks or [encoded])
        self.headers = {"Content-Type": "application/json"}
        self.closed = False

    def iter_content(self, chunk_size):
        del chunk_size
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeProviderSession:
    def __init__(self, response, *, delay=0):
        self.response = response
        self.delay = delay
        self.calls = []

    def post(self, url, **kwargs):
        if self.delay:
            time.sleep(self.delay)
        self.calls.append((url, kwargs))
        return self.response


class ProviderHttpTestCase(unittest.TestCase):
    def test_provider_response_stops_at_two_megabytes(self):
        from app.services.provider_http import (
            ProviderResponseTooLarge,
            post_json_bounded,
        )

        response = FakeProviderResponse(
            chunks=[b"x" * 1_500_000, b"y" * 1_500_000]
        )
        session = FakeProviderSession(response)

        with self.assertRaises(ProviderResponseTooLarge):
            post_json_bounded(
                "https://provider.example/api",
                headers={"Authorization": "Bearer secret"},
                payload={"messages": []},
                proxies=None,
                session=session,
            )

        self.assertTrue(response.closed)

    def test_provider_response_is_parsed_only_after_bounded_read(self):
        from app.services.provider_http import post_json_bounded

        response = FakeProviderResponse(payload={"result": "safe"})
        session = FakeProviderSession(response)

        result = post_json_bounded(
            "https://provider.example/api",
            headers={},
            payload={"messages": []},
            proxies=None,
            session=session,
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, {"result": "safe"})
        self.assertTrue(session.calls[0][1]["stream"])
        self.assertEqual(session.calls[0][1]["timeout"], (5, 30))


class ProviderHttpAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_async_provider_call_does_not_block_peer_coroutine(self):
        from app.services.provider_http import async_post_json_bounded

        session = FakeProviderSession(
            FakeProviderResponse(payload={"result": "safe"}),
            delay=0.15,
        )
        provider_task = asyncio.create_task(
            async_post_json_bounded(
                "https://provider.example/api",
                headers={},
                payload={},
                proxies=None,
                total_timeout=1,
                session=session,
            )
        )

        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.05)
        result = await provider_task
        self.assertEqual(result.data, {"result": "safe"})


if __name__ == "__main__":
    unittest.main()
