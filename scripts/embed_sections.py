"""Chunk stored filing sections and embed them with a local Ollama model (issue #2, step 3).

python scripts/embed_sections.py --model nomic-embed-text
python scripts/embed_sections.py --model bge-m3 --cik 2130357
"""

from __future__ import annotations

import argparse
import time

from _bootstrap import bootstrap

from app.services import semantic_search
from app.services.sec_client import normalize_cik


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", choices=sorted(semantic_search.MODELS), required=True)
    parser.add_argument("--cik", action="append", help="Only this company (repeatable)")
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    try:
        ciks = [normalize_cik(c) for c in args.cik] if args.cik else None
        t = time.perf_counter()
        n = semantic_search.index_sections(db, settings, args.model, ciks=ciks)
        print(f"{args.model}: embedded {n} chunks in {time.perf_counter() - t:.0f}s", flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
