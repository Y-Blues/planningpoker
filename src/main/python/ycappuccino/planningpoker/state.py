"""A room's state as everyone holding its link sees it, read from the store each time (nothing kept): the participants
(whether each voted; their card once revealed), the current task, its results, the finished tasks."""

import re
import time

from ycappuccino.api.storage import IManager

from ycappuccino.planningpoker.api import PARTICIPANT_ITEM, ROOM_ITEM, TASK_ITEM, VOTE_ITEM
from ycappuccino.planningpoker.deck import default_avatar, results, value

_ALL = 1000  # far above the caps (participants, tasks)


def fields(model) -> dict:
    return model.get_storage_model() if model is not None else {}


async def records(manager: IManager, item: str, query: dict) -> list:
    return [fields(model) for model in await manager.get_many(item, {"filter": query, "limit": _ALL})]


def _natural(number: str) -> list:
    """KP-9 before KP-10"""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", number or "")]


def forest(nodes: list) -> list:
    """the nodes ({number, parent, ...}) as trees by `parent` (children sorted by number, `children` added); a node
    whose parent is unknown, itself or in a loop is a root"""
    by_number = {node["number"]: {**node, "children": []} for node in nodes}

    def loops(number: str) -> bool:
        seen, current = set(), number
        while current in by_number and current not in seen:
            seen.add(current)
            current = by_number[current].get("parent")
        return current in seen

    roots = []
    for number in sorted(by_number, key=_natural):
        node = by_number[number]
        parent = by_number.get(node.get("parent"))
        if parent is None or loops(number):
            roots.append(node)
        else:
            parent["children"].append(node)
    return roots


def _totals(node: dict) -> float:
    """node["total"]: the numeric finals of its descendants (its own final aside); returns that plus its own"""
    below = sum(_totals(child) for child in node["children"])
    node["total"] = below
    return below + (value(node.get("final") or "") or 0)


def recap_tree(tasks: list, others: list = ()) -> list:
    """the finished tasks as a tree (a parent that was never played is a node without final, with the title and kind
    of the room's other tasks when it has one), each node with the total of its descendants' numeric finals"""
    unplayed = {task["number"]: task for task in others}
    known = {task["number"] for task in tasks}
    nodes = [{"number": task["number"], "title": task.get("title") or "", "kind": task.get("kind") or "",
              "parent": task.get("parent"), "final": task.get("final") or ""} for task in tasks]
    for task in tasks:
        parent = task.get("parent")
        if parent and parent not in known and parent != task["number"]:
            known.add(parent)
            seen = unplayed.get(parent) or {}
            nodes.append({"number": parent, "title": seen.get("title") or "", "kind": seen.get("kind") or "",
                          "parent": seen.get("parent"), "final": ""})
    roots = forest(nodes)
    for root in roots:
        _totals(root)
    return roots


def queue_tree(tasks: list) -> list:
    """the imported tasks not played yet, as a tree"""
    return forest([{"number": task["number"], "title": task.get("title") or "", "kind": task.get("kind") or "task",
                    "parent": task.get("parent")} for task in tasks if task.get("queued")])


async def room_state(manager: IManager, room_id: str) -> dict | None:
    room = fields(await manager.get_one(ROOM_ITEM, room_id))
    if not room:
        return None
    people = sorted(await records(manager, PARTICIPANT_ITEM, {"room": room_id}),
                    key=lambda record: (record.get("joined_at") or 0, record["_id"]))
    tasks = sorted(await records(manager, TASK_ITEM, {"room": room_id}), key=lambda record: record.get("order") or 0)
    task = next((record for record in tasks if record["_id"] == room.get("task")), None)
    votes = {vote["participant"]: vote["card"] for vote in await records(manager, VOTE_ITEM, {"task": task["_id"]})} \
        if task else {}
    revealed = bool(task and task.get("revealed"))
    present = {person["_id"] for person in people}
    return {
        "room": room_id,
        "stamp": time.time_ns(),  # newer state wins in a browser receiving two out of order
        "host": room.get("host"),
        "locked": bool(room.get("locked")),
        "participants": [{"id": person["_id"], "nickname": person.get("nickname"),
                          "avatar": person.get("avatar") or default_avatar(person.get("nickname") or ""), "voted": person["_id"] in votes,
                          "card": votes.get(person["_id"]) if revealed else None} for person in people],
        "task": {"id": task["_id"], "number": task.get("number"), "title": task.get("title") or "", "revealed": revealed,
                 "final": task.get("final") or ""} if task else None,
        "results": results([card for who, card in votes.items() if who in present]) if revealed else None,
        "tasks": [{"number": record.get("number"), "final": record.get("final") or ""}
                  for record in tasks if record.get("revealed")],
        "recap": recap_tree([record for record in tasks if record.get("revealed")], tasks),
        "queue": queue_tree(tasks),
    }
