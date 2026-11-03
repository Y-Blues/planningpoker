from ycappuccino.api.decorators import Item, Property
from ycappuccino.api.models import Model
from ycappuccino.core.decorator_app import Dimension


@Dimension(name="planningpoker")
@Item(collection="poker_votes", name="poker_vote", plural="poker_votes")
class PokerVote(Model):
    """a participant's card on a task, hidden until revealed"""

    def __init__(self, a_dict: dict | None = None) -> None:
        super().__init__(a_dict)
        for name in ('room', 'task', 'participant', 'card'):
            setattr(self, "_" + name, None)

    @Property(name="room", type="string", maxLength=200)
    def room(self, a_value) -> None:
        """the room's id"""
        self._room = a_value

    @Property(name="task", type="string", maxLength=200)
    def task(self, a_value) -> None:
        """the task's id"""
        self._task = a_value

    @Property(name="participant", type="string", maxLength=200)
    def participant(self, a_value) -> None:
        """the participant's id"""
        self._participant = a_value

    @Property(name="card", type="string", maxLength=200)
    def card(self, a_value) -> None:
        """a card of the deck"""
        self._card = a_value
