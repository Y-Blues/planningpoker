"""RoomEvents: a room's upsert (every action ends with one, rooms.PlanningPoker._touched) publishes its new state on
its topic (api.room_topic), read from the store."""

from ycappuccino.api.models import Model
from ycappuccino.api.pubsub import IPublisher
from ycappuccino.api.storage import IManager, ITrigger

from ycappuccino.planningpoker.api import ROOM_ITEM, room_topic
from ycappuccino.planningpoker.state import room_state


class RoomEvents(ITrigger):
    item_id = ROOM_ITEM
    actions = ("upsert",)
    post = True

    def __init__(self, manager: IManager, publisher: IPublisher) -> None:
        self._manager = manager
        self._publisher = publisher

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def execute(self, action: str, item_id: str, model: Model) -> None:
        room = model.get_storage_model().get("_id")
        state = await room_state(self._manager, room) if room else None
        if state is not None:
            await self._publisher.publish(room_topic(room), state)
