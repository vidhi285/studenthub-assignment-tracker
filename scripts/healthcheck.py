#!/usr/bin/env python3
"""Check a StudentHub /health endpoint. Uses only the standard library.

Examples
    python scripts/healthcheck.py                                   # http://127.0.0.1:5000/health
    python scripts/healthcheck.py https://example.com/health --retries 10 --delay 6
    python scripts/healthcheck.py URL --expect-version <git sha>    # also verify the deployed version

Exit code 0 means healthy (and the expected version, if given); 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def check(url: str, expect_version: str | None, timeout: float) -> tuple[bool, str]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "studenthub-healthcheck"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            body = {}
        return False, f"HTTP {exc.code} status={body.get('status')} database={body.get('database')}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"request failed: {exc}"
    if body.get("status") != "ok":
        return False, f"status={body.get('status')} database={body.get('database')}"
    if expect_version and body.get("version") != expect_version:
        return False, f"version is {body.get('version')!r}, expected {expect_version!r}"
    return True, f"healthy version={body.get('version')} migrations={body.get('migrations_applied')}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:5000/health")
    parser.add_argument("--expect-version")
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    message = ""
    for attempt in range(1, max(args.retries, 1) + 1):
        ok, message = check(args.url, args.expect_version, args.timeout)
        if ok:
            if not args.quiet:
                print(f"OK {args.url}: {message}")
            return 0
        if attempt < args.retries:
            if not args.quiet:
                print(f"attempt {attempt}/{args.retries} not healthy yet: {message}")
            time.sleep(args.delay)
    print(f"UNHEALTHY {args.url}: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
