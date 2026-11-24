"""Reddit source validation tests (SSRF guards, whitelist enforcement)."""
from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, patch


async def test_invalid_subreddit_returns_empty(tmp_workdir):
    from backend.services.sources import reddit
    assert await reddit.fetch("../../etc/passwd") == []
    assert await reddit.fetch("has spaces") == []
    assert await reddit.fetch("") == []
    assert await reddit.fetch("a" * 100) == []


def _fake_fetch(captured, payload=None):
    """Stand-in for the synchronous urllib helper used by reddit.fetch."""
    def _fetch(url, params, user_agent):
        captured["url"] = url
        captured["params"] = params
        captured["user_agent"] = user_agent
        return payload if payload is not None else {"data": {"children": []}}
    return _fetch


async def test_valid_subreddit_normalises_sort_and_t(tmp_workdir):
    from backend.services.sources import reddit
    captured = {}
    with patch("backend.services.sources.reddit._fetch_reddit_json", _fake_fetch(captured)):
        out = await reddit.fetch("earthporn", sort="evilsort", t="evilt", limit=999)
    assert out == []
    assert "earthporn" in captured["url"]
    # invalid sort defaulted in URL "/top.json"
    assert "/top.json" in captured["url"]
    assert captured["params"]["t"] == "week"
    assert captured["params"]["limit"] == 100  # clamped from 999


async def test_limit_clamped_low(tmp_workdir):
    """limit < 1 clamps to 1."""
    from backend.services.sources import reddit
    captured = {}
    with patch("backend.services.sources.reddit._fetch_reddit_json", _fake_fetch(captured)):
        await reddit.fetch("aww", limit=-5)
    assert captured["params"]["limit"] == 1


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
            ]
        }
    }
    with patch("backend.services.sources.reddit._fetch_reddit_json", _fake_fetch({}, payload)):
        out = await reddit.fetch("pics")

    assert out[0]["url"] == "https://i.redd.it/test.jpeg"
    assert out[0]["thumb"] == "https://preview.redd.it/test.jpeg?width=140&height=93&auto=webp"
