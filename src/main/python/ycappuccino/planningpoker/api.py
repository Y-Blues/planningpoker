"""The planning poker's port: IPlanningPoker, called by the browser over WS-RPC. Anonymous on purpose (secure=False):
each call carries the browser's secret, which the service binds to one nickname per room (anti-impersonation)."""

from abc import ABC, abstractmethod

from ycappuccino.api.core_base import YCappuccinoComponent
from ycappuccino.api.decorators import rpc_method

ROOM_ITEM = "poker_room"
PARTICIPANT_ITEM = "poker_participant"
TASK_ITEM = "poker_task"
VOTE_ITEM = "poker_vote"
TOPIC_PREFIX = "planningpoker."
NOT_FOUND = "Salle introuvable."


def room_topic(room: str) -> str:
    """the topic a room's state is published on"""
    return TOPIC_PREFIX + room


class IPlanningPoker(YCappuccinoComponent, ABC):
    """every answer is the room's state (state.room_state) with `me`, the caller's participant id (None: not joined)"""

    @abstractmethod
    @rpc_method(summary="create a room, its creator joining as host", secure=False)
    async def create_room(self, secret: str, nickname: str, avatar: str = "") -> dict:
        """a new room (random, unguessable id) hosted by this browser; avatar: one of deck.AVATARS (\"\": by nickname)"""

    @abstractmethod
    @rpc_method(summary="join a room by nickname", secure=False)
    async def join(self, room: str, secret: str, nickname: str, avatar: str = "") -> dict:
        """the nickname bound to this secret in the room; refused when another secret holds it"""

    @abstractmethod
    @rpc_method(summary="change this participant's nickname", secure=False)
    async def rename(self, room: str, secret: str, nickname: str) -> dict:
        """the caller's own nickname, unique in the room (same rules as join)"""

    @abstractmethod
    @rpc_method(summary="change this participant's avatar", secure=False)
    async def set_avatar(self, room: str, secret: str, avatar: str) -> dict:
        """one of deck.AVATARS, the caller's own only"""

    @abstractmethod
    @rpc_method(summary="a room's state", secure=False)
    async def state(self, room: str, secret: str) -> dict:
        """the room as anyone holding its link sees it"""

    @abstractmethod
    @rpc_method(summary="tell the room this participant is still here", secure=False)
    async def ping(self, room: str, secret: str) -> dict:
        """the heartbeat: a host unseen for a while hands the room over to the next participant present"""

    @abstractmethod
    @rpc_method(summary="vote on the current task", secure=False)
    async def vote(self, room: str, secret: str, card: str) -> dict:
        """a card of the deck, "" withdraws the vote"""

    @abstractmethod
    @rpc_method(summary="reveal the votes (host)", secure=False)
    async def reveal(self, room: str, secret: str) -> dict:
        """the votes shown, the task's final estimate set to the nearest card"""

    @abstractmethod
    @rpc_method(summary="vote again on the current task (host)", secure=False)
    async def revote(self, room: str, secret: str) -> dict:
        """the votes cleared, hidden again"""

    @abstractmethod
    @rpc_method(summary="set the current task's final estimate (host)", secure=False)
    async def set_final(self, room: str, secret: str, card: str) -> dict:
        """a card of the deck, once revealed"""

    @abstractmethod
    @rpc_method(summary="start the next task by its number (host)", secure=False)
    async def next_task(self, room: str, secret: str, number: str, parent: str = "") -> dict:
        """a new task to vote on; parent: the number of the epic or story it belongs to (optional); a queued (imported)
        task of that number is the one played"""

    @abstractmethod
    @rpc_method(summary="queue tickets imported from a tracker (host)", secure=False)
    async def import_tasks(self, room: str, secret: str, items: list) -> dict:
        """items: [{key, title, kind (epic|story|subtask|task), parent}], rate-limited and capped; a ticket already in
        the room has its title, kind and parent updated, its votes and final kept; new ones wait in the queue"""

    @abstractmethod
    @rpc_method(summary="remove a participant (host)", secure=False)
    async def remove(self, room: str, secret: str, participant: str) -> dict:
        """the participant and their vote removed"""

    @abstractmethod
    @rpc_method(summary="lock or unlock the room to new participants (host)", secure=False)
    async def lock(self, room: str, secret: str, locked: bool) -> dict:
        """locked: nobody new may join"""


class IRateLimits(YCappuccinoComponent, ABC):
    """per visitor address (api.http_server.VISITOR_ADDRESS) limits of a kind of call"""

    @abstractmethod
    def check(self, kind: str) -> None:
        """InvalidRequest when the visitor reached the kind's limit"""

    @abstractmethod
    def count(self, kind: str) -> None:
        """one more call (or failure) of the kind for the visitor"""
