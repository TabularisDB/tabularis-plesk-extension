#!/usr/bin/env python3
"""Check real HTTP/WebSocket isolation after verify.py --with-panel."""

import argparse
import asyncio
import json
import re
import time
from urllib.parse import urlsplit

import aiohttp

from provision import STATE, assert_lab, plesk
from verify import require


def cookies(label):
    values = json.loads((STATE / f"{label}-cookies.json").read_text())
    return "; ".join(f"{name}={value}" for name, value in values.items())


async def verify_runtime(origin):
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as client:
        async def request(path, label=None):
            headers = {"Cookie": cookies(label)} if label else {}
            async with client.get(origin + path, headers=headers, allow_redirects=False) as response:
                await response.read()
                return response.status, response.headers.get("Location")

        status, target = await request("/tabularis/open/1", "subuser")
        require(status in (302, 303), "The permitted subuser could not open its runtime.")
        match = re.match(r"(/tabularis/w/[^/]+/)", target or "")
        require(match is not None, "The gateway did not return a workspace route.")
        prefix = match.group(1)
        require((await request(prefix + "healthz", "subuser"))[0] == 200, "The permitted runtime is not healthy.")
        for other in ("customer", "denied", None):
            require((await request(prefix + "healthz", other))[0] in (401, 403), "A different principal reused a workspace URL.")
        require((await request("/tabularis/open/1", "denied"))[0] == 403, "The denied subuser opened a runtime.")
        print("PASS gateway: allowed subuser opens runtime; customer/denied/anonymous cannot reuse its URL")

        websocket = await client.ws_connect(origin + prefix + "api/v1/events", headers={"Cookie": cookies("subuser"), "Origin": origin})
        try:
            started = time.monotonic()
            plesk(["role", "--update", "LabDatabaseUser", "-owner", "tabularis-lab", "-databasesManagement", "false"])
            # No HTTP request triggers reconciliation: the established socket must
            # discover revocation through its own periodic permission check.
            while True:
                message = await asyncio.wait_for(websocket.receive(), timeout=8)
                if message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
            elapsed = time.monotonic() - started
            require(elapsed < 8, "An established WebSocket survived role revocation.")
            require((await request(prefix + "healthz", "subuser"))[0] == 403, "HTTP access survived role revocation.")
            print(f"PASS gateway: established WebSocket independently revoked in {elapsed:.2f}s; HTTP access denied")
        finally:
            plesk(["role", "--update", "LabDatabaseUser", "-owner", "tabularis-lab", "-databasesManagement", "true"])
            await websocket.close()
        require((await request("/tabularis/open/1", "subuser"))[0] in (302, 303), "The restored role could not open a fresh runtime.")
        print("PASS gateway: restored database role opens a fresh authorized runtime")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True, help="Public HTTPS panel origin with a valid certificate")
    arguments = parser.parse_args()
    url = urlsplit(arguments.origin)
    require(url.scheme == "https" and url.hostname and not url.username and not url.password
            and not url.query and not url.fragment and url.path in ("", "/"), "Use an HTTPS origin without a path or credentials.")
    assert_lab()
    asyncio.run(verify_runtime(arguments.origin.rstrip("/")))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, asyncio.TimeoutError, aiohttp.ClientError):
        # Library exceptions can contain a session-specific workspace URL.
        raise SystemExit("Runtime verification failed; inspect the lab privately. No session values were printed.") from None
