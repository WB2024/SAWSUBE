"""download_and_register: never leaves junk files behind, caps download size."""
from __future__ import annotations
import os
import httpx
import pytest


def _files(tmp_workdir):
    root = tmp_workdir / "data" / "images"
    return sorted(p.name for p in root.rglob("*") if p.is_file())


@pytest.fixture()
def serve(monkeypatch, tmp_workdir):
    """Route the downloader's HTTP client to a handler."""
    def _serve(handler):
        from backend.services.sources import common
        monkeypatch.setattr(common, "_http_client",
                            lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return common
    return _serve


async def test_valid_image_is_registered(serve, jpeg_bytes, tmp_workdir):
    from backend.database import init_db
    await init_db()
    data = jpeg_bytes()
    common = serve(lambda req: httpx.Response(200, content=data, headers={"content-type": "image/jpeg"}))
    img = await common.download_and_register("https://example.com/a.jpg", "test", "a.jpg", {})
    assert img is not None and img.source == "test"
    assert _files(tmp_workdir) == ["a.jpg"]


async def test_non_image_is_rejected_and_deleted(serve, tmp_workdir):
    from backend.database import init_db
    await init_db()
    common = serve(lambda req: httpx.Response(200, content=b"<html>Access denied</html>",
                                              headers={"content-type": "text/html"}))
    assert await common.download_and_register("https://example.com/a.jpg", "test", "a.jpg", {}) is None
    assert _files(tmp_workdir) == []


async def test_http_error_returns_none_without_file(serve, tmp_workdir):
    common = serve(lambda req: httpx.Response(403, content=b"forbidden"))
    assert await common.download_and_register("https://example.com/a.jpg", "test", "a.jpg", {}) is None
    assert _files(tmp_workdir) == []


async def test_declared_size_over_limit_is_refused(serve, tmp_workdir, monkeypatch):
    common = serve(lambda req: httpx.Response(200, content=b"x" * 2048))
    monkeypatch.setattr(common, "MAX_DOWNLOAD_BYTES", 1024)
    assert await common.download_and_register("https://example.com/a.jpg", "test", "a.jpg", {}) is None
    assert _files(tmp_workdir) == []


async def test_streamed_size_over_limit_is_refused(serve, tmp_workdir, monkeypatch):
    async def endless():
        for _ in range(100):
            yield b"x" * 512

    common = serve(lambda req: httpx.Response(200, content=endless()))  # no content-length
    monkeypatch.setattr(common, "MAX_DOWNLOAD_BYTES", 4096)
    assert await common.download_and_register("https://example.com/a.jpg", "test", "a.jpg", {}) is None
    assert _files(tmp_workdir) == []


async def test_duplicate_download_reuses_existing_image(serve, jpeg_bytes, tmp_workdir):
    from backend.database import init_db
    await init_db()
    data = jpeg_bytes()
    common = serve(lambda req: httpx.Response(200, content=data))
    first = await common.download_and_register("https://example.com/a.jpg", "test", "a.jpg", {})
    second = await common.download_and_register("https://example.com/a.jpg", "test", "a.jpg", {})
    assert second.id == first.id
    assert _files(tmp_workdir) == ["a.jpg"]


async def test_downloads_send_descriptive_user_agent(tmp_workdir):
    from backend.services.sources import common
    client = common._http_client()
    try:
        ua = client.headers["user-agent"]
    finally:
        await client.aclose()
    assert ua == common.USER_AGENT
    assert ua.startswith("SAWSUBE/") and "python-httpx" not in ua


class _FakeUrlopenResponse:
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body, self._pos = body, 0
        self.headers = headers or {}

    def read(self, n=-1):
        chunk = self._body[self._pos:self._pos + n] if n > 0 else self._body[self._pos:]
        self._pos += len(chunk)
        return chunk

    def __enter__(self): return self
    def __exit__(self, *a): return False


@pytest.fixture()
def fake_urlopen(monkeypatch, tmp_workdir):
    from backend.services.sources import common
    seen = []

    def install(body, headers=None, error=None):
        def urlopen(req, context=None, timeout=None):
            seen.append(req)
            if error:
                raise error
            return _FakeUrlopenResponse(body, headers)
        monkeypatch.setattr(common.urllib.request, "urlopen", urlopen)
        return common
    install.seen = seen
    return install


async def test_urllib_downloader_registers_image(fake_urlopen, jpeg_bytes, tmp_workdir):
    from backend.database import init_db
    await init_db()
    common = fake_urlopen(jpeg_bytes())
    img = await common.download_and_register("https://images.example/a.jpg", "met", "a.jpg", {},
                                             downloader=common.download_urllib)
    assert img is not None
    assert fake_urlopen.seen[0].get_header("User-agent") == common.USER_AGENT
    assert _files(tmp_workdir) == ["a.jpg"]


async def test_urllib_downloader_bot_page_is_rejected(fake_urlopen, tmp_workdir):
    from backend.database import init_db
    await init_db()
    common = fake_urlopen(b"<html>Pardon Our Interruption</html>", {"Content-Type": "text/html"})
    assert await common.download_and_register("https://images.example/a.jpg", "met", "a.jpg", {},
                                              downloader=common.download_urllib) is None
    assert _files(tmp_workdir) == []


async def test_urllib_downloader_http_error(fake_urlopen, tmp_workdir):
    import urllib.error
    common = fake_urlopen(b"", error=urllib.error.HTTPError("u", 403, "Forbidden", {}, None))
    assert await common.download_and_register("https://images.example/a.jpg", "met", "a.jpg", {},
                                              downloader=common.download_urllib) is None
    assert _files(tmp_workdir) == []


@pytest.mark.parametrize("headers", [{"Content-Length": "5000"}, {}])
async def test_urllib_downloader_size_cap(fake_urlopen, tmp_workdir, monkeypatch, headers):
    common = fake_urlopen(b"x" * 5000, headers)
    monkeypatch.setattr(common, "MAX_DOWNLOAD_BYTES", 1024)
    assert await common.download_and_register("https://images.example/a.jpg", "met", "a.jpg", {},
                                              downloader=common.download_urllib) is None
    assert _files(tmp_workdir) == []
