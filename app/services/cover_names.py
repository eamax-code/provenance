"""Company names as the SEC carries them, made readable without changing what they say (K-06).

- The SEC's notes data sets take dei:EntityRegistrantName from the cover's HTML with the tags
  removed, so "NIO<span>Inc.</span>" arrives as "NIOInc.": a legal form glued to the word before
  it gets its space back. Words are never joined.
- The conformed name's state suffix ("COSTCO WHOLESALE CORP /NEW", "QUALCOMM INC/DE", "TOYOTA
  MOTOR CORP/") is dropped, but never from a name ending in a legal form written with a slash
  (Novo Nordisk A/S, Banco Bradesco S/A, N/V): "/S" there is not a state.
"""

from __future__ import annotations

import re

_GLUED_FORM = re.compile(r"(?<=[A-Za-z0-9)])(?<![PL])(Inc\.?|Ltd\.?|LLC|N\.V\.|S\.A\.|plc)$")
_SLASH_FORM = re.compile(r"(?:^|\s)(?:A/S|S/A|N/V|AG/S|I/S|K/S|P/S|AB/S|AS/S)\.?$", re.I)
_EDGAR_SUFFIX = re.compile(r"\s*/[A-Z]{0,5}/?\s*$")  # "/DE/", "/FA", " /NEW", a trailing "/"


def unglue(name: str | None) -> str | None:
    """'NIOInc.' -> 'NIO Inc.', 'PDD HoldingsInc.' -> 'PDD Holdings Inc.'; 'Apple Inc.' as is."""
    return _GLUED_FORM.sub(r" \1", name.strip()) if name else name


def strip_state_suffix(name: str) -> str:
    name = name.strip()
    if _SLASH_FORM.search(name):
        return name
    return _EDGAR_SUFFIX.sub("", name).strip()
