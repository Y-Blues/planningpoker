"""The Jira import's browser side, without DOM: the bookmarklet's link and the messages the room page accepts.
Read only: the bookmarklet reads Jira with the user's own session, nothing is ever written to Jira."""

import json
import re
from importlib import resources
from urllib.parse import quote

from ycappuccino.planningpoker.deck import IMPORT_MAX, ticket

READY, HELLO, IMPORT = "planningpoker:ready", "planningpoker:hello", "planningpoker:import"
_ORIGIN = re.compile(r"https://[a-z0-9][a-z0-9-]*\.atlassian\.net")


def bookmarklet(room_url: str) -> str:
    """the javascript: link of static/jira_bookmarklet.js for a room's URL (the URL only, never the browser's secret):
    comment lines and indentation dropped, lines joined"""
    source = resources.files("ycappuccino.planningpoker").joinpath("static/jira_bookmarklet.js").read_text(encoding="utf-8")
    lines = (line.strip() for line in source.splitlines())
    script = " ".join(line for line in lines if line and not line.startswith("//")).replace("__ROOM__", json.dumps(room_url))
    return "javascript:" + quote(script, safe="!$&'()*+,;=:@/?-._~")


def site(origin: str) -> str | None:
    """the Jira site's host (acme.atlassian.net) when the message came from a Jira Cloud page, else None"""
    return origin[len("https://"):] if isinstance(origin, str) and _ORIGIN.fullmatch(origin) else None


def received(origin: str, data) -> tuple[str, list] | None:
    """(site, tickets) of an import message from a Jira Cloud page, the tickets cleaned and capped; None for anything else"""
    host = site(origin)
    if host is None or not isinstance(data, dict) or data.get("type") != IMPORT or not isinstance(data.get("items"), list):
        return None
    tickets = [found for found in map(ticket, data["items"][:IMPORT_MAX]) if found]
    return (host, tickets) if tickets else None
