"""What the page shows of a room's state for one participant, without any DOM: the seats (around the table), the
table's status, what the host may do, the results and the recap."""

import math

from ycappuccino.planningpoker.deck import DECK, format_average, value


def seats(state: dict, me: str | None) -> list:
    """each participant: nickname, avatar, whether it is me / the host, its card's face: "empty" (no vote), "down" (voted,
    hidden), "up" (revealed, with the card)"""
    task = state.get("task") or {}
    revealed = bool(task.get("revealed"))
    result = []
    for person in state.get("participants") or []:
        face = "up" if revealed and person.get("card") else "down" if person.get("voted") else "empty"
        result.append({"id": person["id"], "nickname": person.get("nickname") or "", "avatar": person.get("avatar") or "",
                       "me": person["id"] == me,
                       "host": person["id"] == state.get("host"), "face": face, "card": person.get("card") or ""})
    return result


def split(items: list) -> tuple[list, list]:
    """the seats above the table and those below it, alternately (the table stays balanced)"""
    return items[0::2], items[1::2]


def status(state: dict, me: str | None, t) -> str:
    """the table's line, through t (a ycappuccino.ui Locale's t)"""
    task = state.get("task")
    people = state.get("participants") or []
    if not task:
        return t("poker.status.host_picks") if not is_host(state, me) else t("poker.status.pick_first")
    if task.get("revealed"):
        return t("poker.status.revealed")
    voted = sum(1 for person in people if person.get("voted"))
    if voted == 0:
        return t("poker.status.pick_card")
    return t("poker.status.voted_many" if voted > 1 else "poker.status.voted_one", voted=voted, total=len(people))


def is_host(state: dict, me: str | None) -> bool:
    return me is not None and state.get("host") == me


def my_card(state: dict, me: str | None, chosen: str) -> str:
    """the card I chose for the current task ("" none): mine as the page sent it, forgotten when no longer counted"""
    mine = next((person for person in state.get("participants") or [] if person["id"] == me), None)
    return chosen if mine and mine.get("voted") else ""


def can_vote(state: dict, me: str | None) -> bool:
    task = state.get("task")
    return me is not None and bool(task)   # also after the reveal: a card may still change


AVERAGE = "poker.stat.average"


def results(state: dict, lang: str = "fr") -> list:
    """(label key, value) lines of a revealed vote, its numbers written in lang"""
    summary = state.get("results")
    if not summary:
        return []
    if summary.get("average") is None:
        return [("poker.stat.votes", str(summary.get("votes", 0))), (AVERAGE, "–")]
    return [(AVERAGE, format_average(summary["average"], lang)), ("poker.stat.nearest", summary["nearest"]),
            ("poker.stat.min", summary["min"]), ("poker.stat.max", summary["max"]), ("poker.stat.votes", str(summary["votes"]))]


def distribution(state: dict) -> list:
    """(card, count) of a revealed vote, in deck order"""
    counts = (state.get("results") or {}).get("counts") or {}
    return [(card, counts[card]) for card in DECK if card in counts]


KIND_LABELS = {"epic": "poker.kind.epic", "story": "poker.kind.story", "subtask": "poker.kind.subtask", "task": "poker.kind.task"}   # keys


def flatten(tree: list, depth: int = 0) -> list:
    """a tree's nodes in reading order, each with its depth: [(depth, node)]"""
    rows = []
    for node in tree:
        rows.append((depth, node))
        rows.extend(flatten(node.get("children") or [], depth + 1))
    return rows


STORY_DIVISOR = 8   # a story's total is also shown divided by it, rounded up (owner 2026-11-16)


def divided_up(total: float) -> int:
    """total / STORY_DIVISOR rounded up: 13 -> 2, 16 -> 2, 17 -> 3, 0 -> 0"""
    return math.ceil(total / STORY_DIVISOR)


def recap(state: dict, lang: str = "fr") -> tuple[list, str]:
    """the recap tree as rows (depth, number, title, kind, final, sub: the descendants' total, "" for a leaf, divided:
    a story's sub divided_up, "" for any other row) and the total of every numeric final, numbers written in lang"""
    rows, total = [], 0.0
    for depth, node in flatten(state.get("recap") or []):
        total += value(node.get("final") or "") or 0
        rows.append({"depth": depth, "number": node.get("number") or "", "title": node.get("title") or "",
                     "kind": node.get("kind") or "", "final": node.get("final") or "–",
                     "sub": format_average(node["total"], lang) if node.get("children") else "",
                     "divided": str(divided_up(node["total"])) if node.get("kind") == "story" and node.get("children") else ""})
    return rows, format_average(total, lang)


def moments(before: dict | None, state: dict, me: str | None, mine: str) -> tuple[dict, dict]:
    """what changed since the last drawing, for the page's animations (each plays once, not on every redraw):
    deal (new hand), flip (just revealed), celebrate (just revealed, a consensus), joined / voted (participant ids),
    picked (my card just chosen); and the snapshot to pass as `before` next time (None: the first drawing)"""
    task = state.get("task") or {}
    people = state.get("participants") or []
    now = {"task": task.get("id"), "revealed": bool(task.get("revealed")), "ids": {p["id"] for p in people},
           "voted": {p["id"] for p in people if p.get("voted")}, "mine": mine}
    same_task = before is not None and before["task"] == now["task"]
    flip = same_task and not before["revealed"] and now["revealed"]
    return {
        "deal": bool(task) and not now["revealed"] and (not same_task or before["revealed"]),
        "flip": flip,
        "celebrate": flip and bool((state.get("results") or {}).get("consensus")),
        "joined": now["ids"] - before["ids"] if before is not None else now["ids"],
        "voted": now["voted"] - before["voted"] if same_task and not before["revealed"] else set(),
        "picked": bool(mine) and (before is None or mine != before["mine"]),
    }, now
