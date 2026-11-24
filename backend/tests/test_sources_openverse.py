"""Openverse license choices must map to parameters the API accepts."""
from __future__ import annotations
from unittest.mock import AsyncMock, patch
import pytest


class FakeResponse:
    def raise_for_status(self): pass
    def json(self): return {"results": []}


@pytest.mark.parametrize("choice,expected", [
    ("public_domain", {"license": "cc0,pdm"}),            # not a valid license_type
    ("creative_commons", {"license_type": "all-cc"}),     # API name is all-cc
    ("commercial", {"license_type": "commercial"}),
    ("modification", {"license_type": "modification"}),
    ("", {}),
    ("bogus", {}),
])
async def test_license_choice_maps_to_valid_api_params(tmp_workdir, choice, expected):
    from backend.services.sources import openverse
    captured = {}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, params=None):
            captured.update(params or {})
            return FakeResponse()

    with patch.object(openverse, "_get_auth_headers", new=AsyncMock(return_value={})), \
         patch.object(openverse.httpx, "AsyncClient", FakeClient):
        await openverse.search("monet", license_type=choice)
    got = {k: captured[k] for k in ("license", "license_type") if k in captured}
    assert got == expected


def test_every_ui_choice_has_a_mapping(tmp_workdir):
    from backend.services.sources import openverse
    assert set(openverse.LICENSE_TYPES) - {""} == set(openverse.LICENSE_FILTERS)
