"""Reddit source validation tests (SSRF guards, whitelist enforcement)."""
from __future__ import annotations
import pytest
from unittest.mock import patch

_EMPTY = {"items": [], "next": None}


def _fake_fetcher(response_json: dict, captured: dict | None = None):
    """Stand-in for reddit._fetch_reddit_json (sync, run via executor)."""
    def fetcher(url: str, params: dict, user_agent: str) -> dict:
        if captured is not None:
            captured["url"] = url
            captured["params"] = params
        return response_json
    return fetcher


async def test_invalid_subreddit_returns_empty(tmp_workdir):
    from backend.services.sources import reddit
    assert await reddit.fetch("../../etc/passwd") == _EMPTY
    assert await reddit.fetch("has spaces") == _EMPTY
    assert await reddit.fetch("") == _EMPTY
    assert await reddit.fetch("a" * 100) == _EMPTY


async def test_valid_subreddit_normalises_sort_and_t(tmp_workdir):
    from backend.services.sources import reddit
    captured: dict = {}

    with patch("backend.services.sources.reddit._fetch_reddit_json",
               _fake_fetcher({"data": {"children": []}}, captured)):
        out = await reddit.fetch("earthporn", sort="evilsort", t="evilt", limit=999)
    assert out == _EMPTY
    assert "earthporn" in captured["url"]
    # invalid sort defaulted in URL "/top.json"
    assert "/top.json" in captured["url"]
    assert captured["params"]["t"] == "week"
    assert captured["params"]["limit"] == 100  # clamped from 999


async def test_limit_clamped_low(tmp_workdir):
    """limit < 1 clamps to 1."""
    from backend.services.sources import reddit
    captured: dict = {}

    with patch("backend.services.sources.reddit._fetch_reddit_json",
               _fake_fetcher({"data": {"children": []}}, captured)):
        await reddit.fetch("aww", limit=-5)
    assert captured["params"]["limit"] == 1


async def test_after_param_passed_and_next_returned(tmp_workdir):
    from backend.services.sources import reddit
    captured: dict = {}

    with patch("backend.services.sources.reddit._fetch_reddit_json",
               _fake_fetcher({"data": {"children": [], "after": "t3_xyz"}}, captured)):
        out = await reddit.fetch("pics", after="t3_abc")
    assert captured["params"]["after"] == "t3_abc"
    assert out["next"] == "t3_xyz"


async def test_preview_urls_are_html_unescaped(tmp_workdir):
    from backend.services.sources import reddit

    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "abc",
                        "post_hint": "image",
                        "url": "https://i.redd.it/test.jpeg",
                        "thumbnail": "https://preview.redd.it/test.jpeg?width=140&amp;height=93&amp;auto=webp",
                        "title": "Example",
                        "author": "user",
                        "permalink": "/r/pics/comments/abc/example/",
                        "subreddit": "pics",
                    }
                }
            ],
            "after": None,
        }
    }

    with patch("backend.services.sources.reddit._fetch_reddit_json", _fake_fetcher(payload)):
        out = await reddit.fetch("pics")

    items = out["items"]
    assert items[0]["url"] == "https://i.redd.it/test.jpeg"
    assert items[0]["thumb"] == "https://preview.redd.it/test.jpeg?width=140&height=93&auto=webp"
    assert out["next"] is None
