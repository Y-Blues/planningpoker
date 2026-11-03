from ycappuccino.api.decorators import Item, Property
from ycappuccino.api.models import Model
from ycappuccino.core.decorator_app import Dimension


@Dimension(name="planningpoker")
@Item(collection="poker_rooms", name="poker_room", plural="poker_rooms")
class PokerRoom(Model):
    """a planning poker room: its id is random and unguessable (the link is the key)"""

    def __init__(self, a_dict: dict | None = None) -> None:
        super().__init__(a_dict)
        for name in ('host', 'locked', 'task', 'tasks', 'active_at'):
            setattr(self, "_" + name, None)

    @Property(name="host", type="string", maxLength=200)
    def host(self, a_value) -> None:
        """the host's participant id (the creator)"""
        self._host = a_value

    @Property(name="locked", type="boolean")
    def locked(self, a_value) -> None:
        """nobody new may join"""
        self._locked = a_value

    @Property(name="task", type="string", maxLength=200)
    def task(self, a_value) -> None:
        """the current task's id"""
        self._task = a_value

    @Property(name="tasks", type="integer")
    def tasks(self, a_value) -> None:
        """tasks started, the next one's order"""
        self._tasks = a_value

    @Property(name="active_at", type="number")
    def active_at(self, a_value) -> None:
        """last activity, epoch seconds: an inactive room is purged"""
        self._active_at = a_value
