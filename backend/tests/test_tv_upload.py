"""Uploads apply the selected matte to portrait images as well."""
from __future__ import annotations
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize("matte", ["none", "modern_polar"])
async def test_upload_uses_selected_matte_for_portrait(tmp_workdir, make_jpeg, monkeypatch, matte):
    from backend.services import tv_manager as tm
    calls = []

    class FakeArt:
        async def upload(self, data, **kwargs):
            calls.append(kwargs)
            return "MY_F0001"

    async def fake_new_art(self):
        return FakeArt()

    monkeypatch.setattr(tm.TVConnection, "_new_art", fake_new_art)
    monkeypatch.setattr(tm, "HAS_LIB", True)
    m = tm.TVManager()
    tv = SimpleNamespace(id=1, ip="192.0.2.10", port=8002, mac=None, name="t", token_path=None)
    try:
        assert await m.upload_image(tv, make_jpeg(), matte=matte) == "MY_F0001"
    finally:
        await m.shutdown()
    # samsungframetv defaults portrait_matte to "shadowbox_polar" when omitted
    assert calls == [{"file_type": "JPEG", "matte": matte, "portrait_matte": matte}]
