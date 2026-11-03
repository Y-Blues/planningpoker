"""PlanningPoker: IPlanningPoker on the store (IManager), nothing kept in memory. A caller is the browser's secret: its
sha256 is bound to one nickname per room, so nobody else can act as that nickname. The room's creator is its host
(reveal, revote, final estimate, next task, remove, lock). Every action ends by touching the room (active_at), whose
upsert publishes the new state (RoomEvents). An unknown, malformed or purged room answers the same NOT_FOUND.

    PlanningPoker:
      max_participants: 30
      max_tasks: 300
      expiry_days: 90        # rooms inactive longer are purged when a room is created, and at start
"""

import hashlib
import logging
import secrets
import time

from ycappuccino.api.endpoints_storage import Forbidden, InvalidRequest, NotFound
from ycappuccino.api.storage import IManager

from ycappuccino.planningpoker.api import (NOT_FOUND, PARTICIPANT_ITEM, ROOM_ITEM, TASK_ITEM, VOTE_ITEM, IPlanningPoker,
                                           IRateLimits)
from ycappuccino.planningpoker.deck import DECK, is_room_id, is_secret, nickname, results, task_number
from ycappuccino.planningpoker.state import fields, records, room_state

_logger = logging.getLogger(__name__)

ROOM_ID_BYTES = 24  # 192 bits, 32 URL-safe characters
HOST_ONLY = "Réservé à l'animateur de la salle."
_PURGE_BATCH = 100


def new_id() -> str:
    return secrets.token_urlsafe(ROOM_ID_BYTES)


def secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class PlanningPoker(IPlanningPoker):

    def __init__(self, manager: IManager, limits: IRateLimits, max_participants: int = 30, max_tasks: int = 300,
                 expiry_days: float = 90) -> None:
        self._manager = manager
        self._limits = limits
        self._max_participants = int(max_participants)
        self._max_tasks = int(max_tasks)
        self._expiry = float(expiry_days) * 86400

    async def start(self) -> None:
        try:
            await self.purge()
        except Exception:  # the store not ready yet: the next creation purges
            _logger.warning("expired rooms not purged at start", exc_info=True)

    async def stop(self) -> None:
        pass

    # ------------------------------------------------------------------ anyone

    async def create_room(self, secret: str, nickname: str) -> dict:
        self._limits.check("create")
        name = _nickname(nickname)
        _secret(secret)
        self._limits.count("create")
        await self.purge()
        room = new_id()
        person = new_id()
        await self._manager.up_sert(PARTICIPANT_ITEM, person, {
            "room": room, "nickname": name, "key": name.casefold(), "secret": secret_hash(secret),
            "joined_at": time.time()})
        await self._manager.up_sert(ROOM_ITEM, room, {"host": person, "locked": False, "task": "", "tasks": 0,
                                                      "active_at": time.time()})
        return await self._answer(room, person)

    async def join(self, room: str, secret: str, nickname: str) -> dict:
        record = await self._room(room)
        name = _nickname(nickname)
        _secret(secret)
        self._limits.check("action")
        self._limits.count("action")
        people = await records(self._manager, PARTICIPANT_ITEM, {"room": room})
        mine = next((person for person in people if person.get("secret") == secret_hash(secret)), None)
        holder = next((person for person in people if person.get("key") == name.casefold()), None)
        if holder is not None and holder is not mine:
            raise Forbidden("Ce pseudo est déjà pris dans cette salle.")
        if mine is not None:
            if mine.get("nickname") != name:
                await self._manager.up_sert(PARTICIPANT_ITEM, mine["_id"], {"nickname": name, "key": name.casefold()})
            return await self._touched(room, mine["_id"])
        if record.get("locked"):
            raise Forbidden("La salle est verrouillée : demandez à l'animateur de l'ouvrir.")
        if len(people) >= self._max_participants:
            raise InvalidRequest(f"La salle est pleine ({self._max_participants} participants).")
        person = new_id()
        await self._manager.up_sert(PARTICIPANT_ITEM, person, {
            "room": room, "nickname": name, "key": name.casefold(), "secret": secret_hash(secret),
            "joined_at": time.time()})
        return await self._touched(room, person)

    async def state(self, room: str, secret: str) -> dict:
        await self._room(room)
        person = await self._participant(room, secret) if is_secret(secret) else None
        return await self._answer(room, person["_id"] if person else None)

    async def vote(self, room: str, secret: str, card: str) -> dict:
        record, person = await self._caller(room, secret)
        if card not in DECK and card != "":
            raise InvalidRequest("Carte inconnue.")
        task = fields(await self._manager.get_one(TASK_ITEM, record.get("task"))) if record.get("task") else {}
        if not task or task.get("revealed"):
            raise InvalidRequest("Aucun vote en cours.")
        vote_id = f"{task['_id']}.{person['_id']}"
        if card:
            await self._manager.up_sert(VOTE_ITEM, vote_id, {"room": room, "task": task["_id"],
                                                             "participant": person["_id"], "card": card})
        else:
            await self._manager.delete(VOTE_ITEM, vote_id)
        return await self._touched(room, person["_id"])

    # ------------------------------------------------------------------ the host

    async def reveal(self, room: str, secret: str) -> dict:
        record, person, task = await self._host_task(room, secret)
        if not task.get("revealed"):
            cards = [vote["card"] for vote in await records(self._manager, VOTE_ITEM, {"task": task["_id"]})]
            await self._manager.up_sert(TASK_ITEM, task["_id"], {"revealed": True,
                                                                 "final": results(cards)["nearest"] or ""})
        return await self._touched(room, person["_id"])

    async def revote(self, room: str, secret: str) -> dict:
        record, person, task = await self._host_task(room, secret)
        await self._manager.delete_many(VOTE_ITEM, {"task": task["_id"]})
        await self._manager.up_sert(TASK_ITEM, task["_id"], {"revealed": False, "final": ""})
        return await self._touched(room, person["_id"])

    async def set_final(self, room: str, secret: str, card: str) -> dict:
        record, person, task = await self._host_task(room, secret)
        if card not in DECK:
            raise InvalidRequest("Carte inconnue.")
        if not task.get("revealed"):
            raise InvalidRequest("Révélez les votes d'abord.")
        await self._manager.up_sert(TASK_ITEM, task["_id"], {"final": card})
        return await self._touched(room, person["_id"])

    async def next_task(self, room: str, secret: str, number: str) -> dict:
        record, person = await self._host(room, secret)
        cleaned = task_number(number)
        if cleaned is None:
            raise InvalidRequest("Numéro de tâche invalide (des chiffres uniquement).")
        order = int(record.get("tasks") or 0)
        if order >= self._max_tasks:
            raise InvalidRequest(f"Limite de {self._max_tasks} tâches atteinte : créez une nouvelle salle.")
        current = fields(await self._manager.get_one(TASK_ITEM, record.get("task"))) if record.get("task") else {}
        if current and not current.get("revealed"):  # left unrevealed: forgotten, never recapped
            await self._manager.delete_many(VOTE_ITEM, {"task": current["_id"]})
            await self._manager.delete(TASK_ITEM, current["_id"])
        task = new_id()
        await self._manager.up_sert(TASK_ITEM, task, {"room": room, "number": cleaned, "order": order + 1,
                                                      "revealed": False, "final": ""})
        return await self._touched(room, person["_id"], task=task, tasks=order + 1)

    async def remove(self, room: str, secret: str, participant: str) -> dict:
        record, person = await self._host(room, secret)
        if participant == person["_id"]:
            raise InvalidRequest("L'animateur ne peut pas se retirer.")
        other = fields(await self._manager.get_one(PARTICIPANT_ITEM, str(participant)))
        if other.get("room") == room:
            await self._manager.delete_many(VOTE_ITEM, {"participant": other["_id"]})
            await self._manager.delete(PARTICIPANT_ITEM, other["_id"])
        return await self._touched(room, person["_id"])

    async def lock(self, room: str, secret: str, locked: bool) -> dict:
        record, person = await self._host(room, secret)
        return await self._touched(room, person["_id"], locked=bool(locked))

    # ------------------------------------------------------------------ expiry

    async def purge(self) -> int:
        """the rooms inactive for expiry_days deleted (their participants, tasks and votes by PolymorphicCascade)"""
        cutoff = time.time() - self._expiry
        purged = 0
        while True:
            expired = await self._manager.get_many(ROOM_ITEM, {"filter": {"active_at": {"$lt": cutoff}},
                                                               "limit": _PURGE_BATCH})
            for model in expired:
                await self._manager.delete(ROOM_ITEM, fields(model)["_id"])
            purged += len(expired)
            if len(expired) < _PURGE_BATCH:
                return purged

    # ------------------------------------------------------------------ helpers

    async def _room(self, room: str) -> dict:
        """the room, or NOT_FOUND whatever the cause (no existence oracle); each miss counted against the visitor"""
        self._limits.check("join_failure")
        record = fields(await self._manager.get_one(ROOM_ITEM, room)) if is_room_id(room) else {}
        if not record:
            self._limits.count("join_failure")
            raise NotFound(NOT_FOUND)
        return record

    async def _participant(self, room: str, secret: str) -> dict | None:
        found = await records(self._manager, PARTICIPANT_ITEM, {"room": room, "secret": secret_hash(secret)})
        return found[0] if found else None

    async def _caller(self, room: str, secret: str) -> tuple[dict, dict]:
        record = await self._room(room)
        self._limits.check("action")
        self._limits.count("action")
        person = await self._participant(room, secret) if is_secret(secret) else None
        if person is None:
            raise Forbidden("Rejoignez la salle d'abord.")
        return record, person

    async def _host(self, room: str, secret: str) -> tuple[dict, dict]:
        record, person = await self._caller(room, secret)
        if record.get("host") != person["_id"]:
            raise Forbidden(HOST_ONLY)
        return record, person

    async def _host_task(self, room: str, secret: str) -> tuple[dict, dict, dict]:
        record, person = await self._host(room, secret)
        task = fields(await self._manager.get_one(TASK_ITEM, record.get("task"))) if record.get("task") else {}
        if not task:
            raise InvalidRequest("Aucune tâche en cours.")
        return record, person, task

    async def _touched(self, room: str, person: str, **changes) -> dict:
        """the room's activity stamped (and its changes written): its upsert publishes the state (RoomEvents)"""
        await self._manager.up_sert(ROOM_ITEM, room, {**changes, "active_at": time.time()})
        return await self._answer(room, person)

    async def _answer(self, room: str, person: str | None) -> dict:
        state = await room_state(self._manager, room)
        if state is None:
            raise NotFound(NOT_FOUND)
        return {**state, "me": person}


def _nickname(text: str) -> str:
    name = nickname(text)
    if name is None:
        raise InvalidRequest("Pseudo invalide : 1 à 24 lettres, chiffres, espaces ou . ' - _")
    return name


def _secret(secret: str) -> None:
    if not is_secret(secret):
        raise InvalidRequest("Identité du navigateur invalide : rechargez la page.")
