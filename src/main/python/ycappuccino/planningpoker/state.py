"""A room's state as everyone holding its link sees it, read from the store each time (nothing kept): the participants
(whether each voted; their card once revealed), the current task, its results, the finished tasks."""

import time

from ycappuccino.api.storage import IManager

from ycappuccino.planningpoker.api import PARTICIPANT_ITEM, ROOM_ITEM, TASK_ITEM, VOTE_ITEM
from ycappuccino.planningpoker.deck import results

_ALL = 1000  # far above the caps (participants, tasks)


def fields(model) -> dict:
    return model.get_storage_model() if model is not None else {}


async def records(manager: IManager, item: str, query: dict) -> list:
    return [fields(model) for model in await manager.get_many(item, {"filter": query, "limit": _ALL})]


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
        "participants": [{"id": person["_id"], "nickname": person.get("nickname"), "voted": person["_id"] in votes,
                          "card": votes.get(person["_id"]) if revealed else None} for person in people],
        "task": {"id": task["_id"], "number": task.get("number"), "revealed": revealed,
                 "final": task.get("final") or ""} if task else None,
        "results": results([card for who, card in votes.items() if who in present]) if revealed else None,
        "tasks": [{"number": record.get("number"), "final": record.get("final") or ""}
                  for record in tasks if record.get("revealed")],
    }
