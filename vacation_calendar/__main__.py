"""Entry point: ``python -m vacation_calendar [--port N] [--db PATH] [--host H]``."""

from __future__ import annotations

import argparse

from .server import serve


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vacation_calendar",
        description="Urlaubskalender mit Audit-Trail (vacation calendar with audit trail).",
    )
    parser.add_argument("--db", default="vacation_calendar.db", help="SQLite database path")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    serve(args.db, args.host, args.port, verbose=args.verbose)


if __name__ == "__main__":
    main()
