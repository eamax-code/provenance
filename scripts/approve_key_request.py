#!/usr/bin/env python
"""Review self-serve key requests.

  python scripts/approve_key_request.py list
  python scripts/approve_key_request.py approve <request_id> [--plan free] [--email]
  python scripts/approve_key_request.py reject <request_id> --reason "..."

With --email and SMTP configured the key is emailed to the requester; otherwise it is printed
once and you deliver it yourself.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from _bootstrap import bootstrap

from app.core.config import PLAN_NAMES
from app.services.key_requests import approve_request, list_pending, reject_request


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    ap = sub.add_parser("approve")
    ap.add_argument("request_id")
    ap.add_argument("--plan", default="free", choices=list(PLAN_NAMES))
    ap.add_argument("--email", action="store_true", help="Email the key (requires SMTP config)")
    rj = sub.add_parser("reject")
    rj.add_argument("request_id")
    rj.add_argument("--reason", required=True)
    args = parser.parse_args()
    settings, Session = bootstrap()
    db = Session()
    try:
        if args.cmd == "list":
            for r in list_pending(db):
                print(f"{r.id}  {r.created_at:%Y-%m-%d %H:%M}  {r.email}  plan={r.requested_plan}")
                print(f"    {r.use_case[:160]}")
            return 0
        rid = uuid.UUID(args.request_id)
        if args.cmd == "reject":
            reject_request(db, rid, args.reason, actor="script")
            db.commit()
            print("rejected")
            return 0
        via = "email" if args.email else "operator"
        key, raw = approve_request(
            db, settings, rid, plan=args.plan, actor="script", delivered_via=via
        )
        if args.email:
            if not settings.email_configured:
                db.rollback()
                print("SMTP is not configured; approve without --email instead.", file=sys.stderr)
                return 2
            from app.services.email_adapter import send_api_key_email

            send_api_key_email(settings, key.owner_email, raw, key.plan)
            db.commit()
            print(f"approved and emailed to {key.owner_email} (key_id={key.id})")
        else:
            db.commit()
            print(f"approved key_id={key.id} plan={key.plan} owner={key.owner_email}")
            print(f"API key (shown once, deliver to the requester): {raw}")
        return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
