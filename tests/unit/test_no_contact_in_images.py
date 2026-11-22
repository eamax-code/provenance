"""The SEC contact address is passed at run time only: never baked into an image or committed in
a deploy file (owner rule; the address is personal)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = ["Dockerfile", "docker-compose.yml", "deploy/fly.toml", "deploy/render.yaml"]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ALLOWED = {"you@example.com", "ops@example.com", "tests@provenance.test"}


def test_no_image_or_deploy_file_sets_a_contact_address():
    for name in FILES:
        path = ROOT / name
        if not path.exists():
            continue
        text = path.read_text()
        # an ENV or a default value for the user agent would bake it into the image
        assert not re.search(r"^\s*ENV\s+SEC_USER_AGENT", text, re.M), name
        assert not re.search(r"^\s*ARG\s+SEC_USER_AGENT", text, re.M), name
        found = {e for e in EMAIL.findall(text) if e not in ALLOWED}
        assert not found, f"{name} contains an address: {sorted(found)}"
