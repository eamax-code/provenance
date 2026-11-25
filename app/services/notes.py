"""N-01: who a response note is for. `notes` stays a list of strings; `notes_detail` gives the same
notes in the same order as {text, audience}: "reader" (shown to people reading the figures:
coverage, caveats, disclaimers, why a figure is missing) or "developer" (documents fields and
parameters: what a field holds, when it is null, how rows are chosen).

A developer note is written as dev("...") where the note is made: a str, so `notes` is
unchanged, tagged so `detail` can tell. Untagged notes are for readers.
"""

from __future__ import annotations

READER, DEVELOPER = "reader", "developer"


class DevNote(str):
    """A note that documents fields or parameters (N-01)."""

    __slots__ = ()


def dev(text: str) -> DevNote:
    return DevNote(text)


def detail(notes: list[str]) -> list[dict]:
    """The notes, in order, each with its audience."""
    return [{"text": str(n), "audience": DEVELOPER if isinstance(n, DevNote) else READER}
            for n in notes]  # fmt: skip


def with_detail(out: dict) -> dict:
    """The response with notes_detail beside its notes."""
    out["notes_detail"] = detail(out.get("notes") or [])
    return out
