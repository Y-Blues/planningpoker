"""RoomTopicAccess: anyone, signed in or not, may follow the topic of any well-formed room id: the unguessable id (the
link) is the key, and answering the same whether the room exists or not leaves no existence oracle (a room nobody
created publishes nothing). Opts in to anonymous subscribers (pubsub's ITopicAccess.admits_anonymous) for these topics
only."""

from ycappuccino.api.pubsub import ITopicAccess

from ycappuccino.planningpoker.api import TOPIC_PREFIX
from ycappuccino.planningpoker.deck import is_room_id


class RoomTopicAccess(ITopicAccess):

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def admits_anonymous(self, topic: str) -> bool:
        return topic.startswith(TOPIC_PREFIX)

    async def may_subscribe(self, subject: dict | None, topic: str) -> bool | None:
        if not topic.startswith(TOPIC_PREFIX):
            return None
        return is_room_id(topic[len(TOPIC_PREFIX):])
