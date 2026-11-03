from ycappuccino.api.decorators import Item, Property
from ycappuccino.api.models import Model
from ycappuccino.core.decorator_app import Dimension


@Dimension(name="planningpoker")
@Item(collection="poker_tasks", name="poker_task", plural="poker_tasks")
class PokerTask(Model):
    """a task voted on in a room, by its number"""

    def __init__(self, a_dict: dict | None = None) -> None:
        super().__init__(a_dict)
        for name in ('room', 'number', 'order', 'revealed', 'final'):
            setattr(self, "_" + name, None)

    @Property(name="room", type="string", maxLength=200)
    def room(self, a_value) -> None:
        """the room's id"""
        self._room = a_value

    @Property(name="number", type="string", maxLength=200)
    def number(self, a_value) -> None:
        """the task's number"""
        self._number = a_value

    @Property(name="order", type="integer")
    def order(self, a_value) -> None:
        """its rank in the room"""
        self._order = a_value

    @Property(name="revealed", type="boolean")
    def revealed(self, a_value) -> None:
        """votes shown"""
        self._revealed = a_value

    @Property(name="final", type="string", maxLength=200)
    def final(self, a_value) -> None:
        """the final estimate, a card"""
        self._final = a_value
