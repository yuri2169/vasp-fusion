"""python -m refportal [--host 127.0.0.1] [--port 8100] [--tool http://127.0.0.1:8000]"""
from __future__ import annotations

import argparse

import uvicorn

from . import NOTICE
from .app import create_app


def main() -> None:
    p = argparse.ArgumentParser(description="A reference SAHYOG portal. " + NOTICE)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--tool", default=None, help="where the tool is reached from here "
                                                 "(or PORTAL_TOOL_URL)")
    p.add_argument("--tool-public", default=None, help="where a browser reaches the tool, "
                                                        "if different (PORTAL_TOOL_PUBLIC_URL)")
    p.add_argument("--db", default=None, help="this portal's own store (PORTAL_DB)")
    args = p.parse_args()
    print(f"{NOTICE} http://{args.host}:{args.port}")
    uvicorn.run(create_app(tool_url=args.tool, tool_public_url=args.tool_public, db=args.db),
                host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
