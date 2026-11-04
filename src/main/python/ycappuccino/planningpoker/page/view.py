"""What the page shows of a room's state for one participant, without any DOM: the seats (around the table), the
table's status, what the host may do, the results and the recap."""

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


def status(state: dict, me: str | None) -> str:
    """the table's line"""
    task = state.get("task")
    people = state.get("participants") or []
    if not task:
        return "L'animateur choisit la première tâche." if not is_host(state, me) else "Choisissez la première tâche."
    if task.get("revealed"):
        return "Cartes révélées"
    voted = sum(1 for person in people if person.get("voted"))
    if voted == 0:
        return "Choisissez une carte"
    return f"{voted} vote{'s' if voted > 1 else ''} sur {len(people)}"


def is_host(state: dict, me: str | None) -> bool:
    return me is not None and state.get("host") == me


def my_card(state: dict, me: str | None, chosen: str) -> str:
    """the card I chose for the current task ("" none): mine as the page sent it, forgotten when no longer counted"""
    mine = next((person for person in state.get("participants") or [] if person["id"] == me), None)
    return chosen if mine and mine.get("voted") else ""


def can_vote(state: dict, me: str | None) -> bool:
    task = state.get("task")
    return me is not None and bool(task) and not task.get("revealed")


def results(state: dict) -> list:
    """(label, value) lines of a revealed vote"""
    summary = state.get("results")
    if not summary:
        return []
    if summary.get("average") is None:
        return [("Votes", str(summary.get("votes", 0))), ("Moyenne", "–")]
    return [("Moyenne", format_average(summary["average"])), ("Carte la plus proche", summary["nearest"]),
            ("Min", summary["min"]), ("Max", summary["max"]), ("Votes", str(summary["votes"]))]


def distribution(state: dict) -> list:
    """(card, count) of a revealed vote, in deck order"""
    counts = (state.get("results") or {}).get("counts") or {}
    return [(card, counts[card]) for card in DECK if card in counts]


def recap(state: dict) -> tuple[list, str]:
    """the finished tasks (number, final) and the total of their numeric finals"""
    tasks = state.get("tasks") or []
    total = sum(value(task.get("final") or "") or 0 for task in tasks)
    return [(task.get("number") or "", task.get("final") or "–") for task in tasks], format_average(total)
