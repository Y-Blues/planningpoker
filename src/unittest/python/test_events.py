import secrets
import unittest

from ycappuccino.planningpoker.api import room_topic
from ycappuccino.planningpoker.topic_access import RoomTopicAccess


class TestRoomTopicAccess(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.access = RoomTopicAccess()

    async def test_anyone_with_a_room_id_follows_its_topic_existing_or_not(self):
        room = room_topic(secrets.token_urlsafe(24))
        self.assertTrue(self.access.admits_anonymous(room))
        self.assertTrue(await self.access.may_subscribe(None, room))  # no existence oracle
        self.assertTrue(await self.access.may_subscribe({"sub": "someone"}, room))

    async def test_a_malformed_room_id_is_refused(self):
        for topic in (room_topic("x"), room_topic("a" * 31 + "/"), room_topic("")):
            self.assertFalse(await self.access.may_subscribe(None, topic))

    async def test_other_topics_are_not_its_own(self):
        self.assertFalse(self.access.admits_anonymous("records.account"))
        self.assertIsNone(await self.access.may_subscribe(None, "records.account"))
