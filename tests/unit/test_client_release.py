"""The Python client is ready to publish and its version matches the API (GH #20)."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "clients" / "python"
sys.path.insert(0, str(CLIENT / "src"))


def test_client_version_matches_the_api():
    import provenance_client

    from app.core.config import Settings

    meta = tomllib.loads((CLIENT / "pyproject.toml").read_text())["project"]
    api = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert meta["version"] == provenance_client.__version__ == api == Settings().app_version
    assert f"## {meta['version']}" in (CLIENT / "CHANGELOG.md").read_text()


def test_client_metadata_is_complete_for_pypi():
    meta = tomllib.loads((CLIENT / "pyproject.toml").read_text())["project"]
    for field in ("description", "readme", "license", "requires-python", "classifiers", "urls"):
        assert meta.get(field), field
    assert (CLIENT / "src" / "provenance_client" / "py.typed").exists()


def test_client_identifies_itself():
    import httpx
    from provenance_client import Client

    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(200, json={"data": []})

    client = Client(api_key="demo", base_url="https://x.test", http=httpx.Client(
        transport=httpx.MockTransport(handler)))  # fmt: skip
    client.search("apple")
    assert seen["user-agent"].startswith("provenance-client/") and seen["x-api-key"] == "demo"
