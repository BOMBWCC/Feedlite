import asyncio
import socket
import time
import unittest


PUBLIC_ADDRESS = "93.184.216.34"


def public_resolver(host, port, *, type):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_ADDRESS, port))]


class FakeResponse:
    def __init__(self, *, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks or [b"ok"])
        self.closed = False

    def iter_content(self, chunk_size):
        del chunk_size
        yield from self._chunks

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requested_urls = []

    def get(self, url, **kwargs):
        self.requested_urls.append((url, kwargs))
        return self.responses.pop(0)


class SafeHttpTestCase(unittest.TestCase):
    def test_rejects_non_http_urls_and_embedded_credentials(self):
        from app.services.safe_http import PublicUrlError, validate_public_http_url

        invalid_urls = (
            "file:///etc/passwd",
            "ftp://example.com/feed",
            "http://user:password@example.com/feed",
            "http:///missing-host",
        )

        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaises(PublicUrlError):
                    validate_public_http_url(url, resolver=public_resolver)

    def test_rejects_loopback_private_link_local_and_mixed_resolution(self):
        from app.services.safe_http import PublicUrlError, validate_public_http_url

        blocked_sets = (
            ["127.0.0.1"],
            ["10.0.0.1"],
            ["169.254.169.254"],
            [PUBLIC_ADDRESS, "192.168.1.2"],
            ["::1"],
        )

        for addresses in blocked_sets:
            def resolver(host, port, *, type, values=addresses):
                del host, type
                family = socket.AF_INET6 if ":" in values[0] else socket.AF_INET
                return [(family, socket.SOCK_STREAM, 6, "", (value, port)) for value in values]

            with self.subTest(addresses=addresses):
                with self.assertRaises(PublicUrlError):
                    validate_public_http_url("https://feed.example/rss", resolver=resolver)

    def test_validates_redirect_target_before_second_request(self):
        from app.services.safe_http import PublicUrlError, fetch_public_bytes

        session = FakeSession(
            [
                FakeResponse(status_code=302, headers={"Location": "http://127.0.0.1/admin"}),
            ]
        )

        with self.assertRaises(PublicUrlError):
            fetch_public_bytes(
                "https://feed.example/rss",
                max_bytes=1024,
                timeout=(3, 10),
                session=session,
                resolver=public_resolver,
            )

        self.assertEqual(len(session.requested_urls), 1)
        self.assertFalse(session.requested_urls[0][1]["allow_redirects"])

    def test_stops_streaming_after_response_byte_limit(self):
        from app.services.safe_http import ResponseTooLargeError, fetch_public_bytes

        response = FakeResponse(chunks=[b"a" * 700, b"b" * 700])
        session = FakeSession([response])

        with self.assertRaises(ResponseTooLargeError):
            fetch_public_bytes(
                "https://feed.example/rss",
                max_bytes=1024,
                timeout=(3, 10),
                session=session,
                resolver=public_resolver,
            )

        self.assertTrue(response.closed)

    def test_rejects_oversized_content_length_before_reading_body(self):
        from app.services.safe_http import ResponseTooLargeError, fetch_public_bytes

        response = FakeResponse(
            headers={"Content-Length": "2048"},
            chunks=[b"small-body"],
        )
        session = FakeSession([response])

        with self.assertRaises(ResponseTooLargeError):
            fetch_public_bytes(
                "https://feed.example/rss",
                max_bytes=1024,
                timeout=(3, 10),
                session=session,
                resolver=public_resolver,
            )

    def test_follows_public_redirect_and_returns_bounded_body(self):
        from app.services.safe_http import fetch_public_bytes

        session = FakeSession(
            [
                FakeResponse(status_code=301, headers={"Location": "/moved"}),
                FakeResponse(chunks=[b"rss", b"-body"]),
            ]
        )

        body = fetch_public_bytes(
            "https://feed.example/rss",
            max_bytes=1024,
            timeout=(3, 10),
            session=session,
            resolver=public_resolver,
        )

        self.assertEqual(body, b"rss-body")
        self.assertEqual(session.requested_urls[1][0], "https://feed.example/moved")


class SafeHttpAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_async_wrapper_keeps_event_loop_responsive(self):
        from app.services.safe_http import async_fetch_public_bytes

        class SlowSession(FakeSession):
            def get(self, url, **kwargs):
                time.sleep(0.15)
                return super().get(url, **kwargs)

        session = SlowSession([FakeResponse(chunks=[b"ok"])])
        request_task = asyncio.create_task(
            async_fetch_public_bytes(
                "https://feed.example/rss",
                max_bytes=1024,
                timeout=(3, 10),
                total_timeout=1,
                session=session,
                resolver=public_resolver,
            )
        )

        await asyncio.wait_for(asyncio.sleep(0.01), timeout=0.05)
        self.assertEqual(await request_task, b"ok")


if __name__ == "__main__":
    unittest.main()
