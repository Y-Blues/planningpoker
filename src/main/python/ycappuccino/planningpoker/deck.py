"""The deck and the rules every side shares (server and browser): cards, results of a vote, input checks."""

import hashlib
import re

DECK = ("0", "1", "2", "3", "5", "8", "13", "21", "34", "55", "89", "?", "☕")   # Fibonacci, no ½ (owner 2026-11-05)
_VALUES = {card: float(card) for card in DECK if card.isdigit()}

AVATARS = ("🦊", "🐼", "🐸", "🦉", "🐙", "🦄", "🐢", "🐝", "🐳", "🦔", "🐧", "🦁", "🍎", "🍋", "🍉", "🥑", "🍄", "🌵", "🚀", "🎸")

NICKNAME_MAX = 24
_NICKNAME = re.compile(r"[^\W_]([\w .'’-]*[^\W_])?")
_TASK_NUMBER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,30}[A-Za-z0-9])?")   # 1234, KP-111, ABC-12.3
_SECRET = re.compile(r"[A-Za-z0-9_-]{32,128}")
_ROOM_ID = re.compile(r"[A-Za-z0-9_-]{22,64}")


def value(card: str) -> float | None:
    """a numeric card's value, None for ? and ☕"""
    return _VALUES.get(card)


def results(cards: list) -> dict:
    """a revealed vote: average of the numeric cards (one decimal), the nearest card (the higher on a tie), min, max,
    the count of each card played, consensus (every vote the same card)"""
    numbers = [value(card) for card in cards if value(card) is not None]
    counts = {card: cards.count(card) for card in DECK if card in cards}
    summary = {"votes": len(cards), "counts": counts, "consensus": len(counts) == 1 and len(cards) > 1,
               "average": None, "nearest": None, "min": None, "max": None}
    if numbers:
        average = sum(numbers) / len(numbers)
        nearest = min(_VALUES, key=lambda card: (abs(_VALUES[card] - average), -_VALUES[card]))
        summary.update(average=round(average, 1), nearest=nearest,
                       min=min(_VALUES, key=lambda card: abs(_VALUES[card] - min(numbers))),
                       max=min(_VALUES, key=lambda card: abs(_VALUES[card] - max(numbers))))
    return summary


def nickname(text: str) -> str | None:
    """the nickname cleaned (spaces collapsed), None when invalid: 1 to NICKNAME_MAX letters, digits, spaces, . ' - _,
    starting and ending with a letter or digit"""
    cleaned = " ".join(str(text or "").split())
    return cleaned if 0 < len(cleaned) <= NICKNAME_MAX and _NICKNAME.fullmatch(cleaned) else None


def avatar(text: str) -> str | None:
    """the avatar if it is one of AVATARS, else None"""
    return text if isinstance(text, str) and text in AVATARS else None


def default_avatar(nickname: str) -> str:
    """the avatar a nickname gets when none is chosen: stable (same nickname, same avatar, whatever the case)"""
    digest = hashlib.sha256(str(nickname).casefold().encode()).digest()
    return AVATARS[int.from_bytes(digest[:4], "big") % len(AVATARS)]


def task_number(text: str) -> str | None:
    """a task number or key (1234, KP-111: letters, digits, - _ . inside, 32 at most, a leading # dropped), None when invalid"""
    cleaned = str(text or "").strip().lstrip("#").strip()
    return cleaned if _TASK_NUMBER.fullmatch(cleaned) else None


def is_secret(text: str) -> bool:
    return isinstance(text, str) and bool(_SECRET.fullmatch(text))


def is_room_id(text: str) -> bool:
    return isinstance(text, str) and bool(_ROOM_ID.fullmatch(text))


def format_average(number: float | None) -> str:
    """French decimal: 4,5"""
    if number is None:
        return "–"
    return (f"{number:.1f}".rstrip("0").rstrip(".")).replace(".", ",")
