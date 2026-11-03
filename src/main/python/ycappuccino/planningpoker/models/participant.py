from ycappuccino.api.decorators import Item, Property
from ycappuccino.api.models import Model
from ycappuccino.core.decorator_app import Dimension


@Dimension(name="planningpoker")
@Item(collection="poker_participants", name="poker_participant", plural="poker_participants")
class PokerParticipant(Model):
    """a nickname in a room, bound to the sha256 of its browser's secret"""

    def __init__(self, a_dict: dict | None = None) -> None:
        super().__init__(a_dict)
        for name in ('room', 'nickname', 'key', 'secret', 'joined_at'):
            setattr(self, "_" + name, None)

    @Property(name="room", type="string", maxLength=200)
    def room(self, a_value) -> None:
        """the room's id"""
        self._room = a_value

    @Property(name="nickname", type="string", maxLength=200)
    def nickname(self, a_value) -> None:
        """as shown"""
        self._nickname = a_value

    @Property(name="key", type="string", maxLength=200)
    def key(self, a_value) -> None:
        """the nickname case-folded: unique in the room"""
        self._key = a_value

    @Property(name="secret", type="string", maxLength=200, private=True)
    def secret(self, a_value) -> None:
        """sha256 of the browser's secret, never sent back"""
        self._secret = a_value

    @Property(name="joined_at", type="number")
    def joined_at(self, a_value) -> None:
        """epoch seconds"""
        self._joined_at = a_value
