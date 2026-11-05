import hashlib
import math
import secrets
import time
import unittest
from unittest import mock
from importlib import resources

import yaml

from ycappuccino.api.decorators import get_rpc_methods
from ycappuccino.api.endpoints_storage import Forbidden, InvalidRequest, NotFound
from ycappuccino.api.http_server import VISITOR_ADDRESS
from ycappuccino.planningpoker.api import (NOT_FOUND, PARTICIPANT_ITEM, ROOM_ITEM, TASK_ITEM, VOTE_ITEM, IPlanningPoker,
                                           room_topic)
from ycappuccino.planningpoker.deck import AVATARS, default_avatar
from ycappuccino.planningpoker.rate_limits import RateLimits
from ycappuccino.planningpoker.room_events import RoomEvents
from ycappuccino.planningpoker.rooms import PlanningPoker

from support import MemoryManager, NoLimits, Publisher


def secret() -> str:
    return secrets.token_urlsafe(32)


class Room(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.manager = MemoryManager()
        self.publisher = Publisher()
        self.manager.triggers.append(RoomEvents(self.manager, self.publisher))
        self.poker = PlanningPoker(self.manager, NoLimits(), max_participants=4, max_tasks=3)
        self.alice, self.bob, self.chloe = secret(), secret(), secret()

    async def room(self) -> str:
        answer = await self.poker.create_room(self.alice, "Alice")
        self.room_id = answer["room"]
        await self.poker.join(self.room_id, self.bob, "Bob")
        return self.room_id


class TestRoomIds(Room):

    async def test_ids_are_random_unguessable_and_url_safe(self):
        rooms = [(await self.poker.create_room(secret(), "Alice"))["room"] for _ in range(200)]
        self.assertEqual(len(set(rooms)), 200)
        for room in rooms:
            self.assertRegex(room, r"^[A-Za-z0-9_-]{32}$")  # 24 random bytes: 192 bits
        self.assertGreaterEqual(len(rooms[0]) * math.log2(64), 128)
        self.assertEqual(len({room[:6] for room in rooms}), 200)  # no shared prefix, no sequence

    async def test_rooms_cannot_be_listed(self):
        self.assertEqual(set(get_rpc_methods(IPlanningPoker)), {
            "create_room", "join", "rename", "set_avatar", "state", "ping", "vote", "reveal", "revote", "set_final", "next_task", "remove", "lock"})
        descriptor = yaml.safe_load(resources.files("ycappuccino.planningpoker").joinpath("ycappuccino_app.yml")
                                    .read_text(encoding="utf-8"))
        bundles = [bundle for part in descriptor["parts"].values() for bundle in part.get("bundles", [])]
        for rest in ("ycappuccino.endpoints_storage", "ycappuccino.http_server"):  # no CRUD API, no REST door
            self.assertFalse(any(bundle.startswith(rest) for bundle in bundles), rest)

    async def test_an_unknown_room_answers_the_same_whatever_the_cause(self):
        room = await self.room()
        await self.manager.delete(ROOM_ITEM, room)  # purged
        for unknown in (room, secrets.token_urlsafe(24), "x", "../etc", "", None):
            for call in (lambda r: self.poker.join(r, self.chloe, "Chloé"), lambda r: self.poker.state(r, self.alice),
                         lambda r: self.poker.vote(r, self.alice, "3"), lambda r: self.poker.reveal(r, self.alice)):
                with self.assertRaises(NotFound) as caught:
                    await call(unknown)
                self.assertEqual(str(caught.exception), NOT_FOUND)


class TestIdentity(Room):

    async def test_the_creator_hosts_and_its_secret_is_kept_hashed(self):
        answer = await self.poker.create_room(self.alice, "Alice")
        self.assertEqual(answer["host"], answer["me"])
        stored = self.manager.of(PARTICIPANT_ITEM)[0]
        self.assertEqual(stored["secret"], hashlib.sha256(self.alice.encode()).hexdigest())
        self.assertNotIn(self.alice, str(answer))
        self.assertNotIn("secret", str(answer))

    async def test_a_nickname_is_bound_to_its_browser(self):
        room = await self.room()
        with self.assertRaisesRegex(Forbidden, "déjà pris"):
            await self.poker.join(room, self.chloe, "  bob ")
        again = await self.poker.join(room, self.bob, "Bobby")  # the same browser: itself, renamed
        self.assertEqual([p["nickname"] for p in again["participants"]], ["Alice", "Bobby"])
        with self.assertRaises(Forbidden):
            await self.poker.vote(room, self.chloe, "3")  # never joined: cannot act

    async def test_invalid_nicknames_and_secrets_are_refused(self):
        room = await self.room()
        for nickname in ("", "<b>x</b>", "x" * 25):
            with self.assertRaises(InvalidRequest):
                await self.poker.join(room, self.chloe, nickname)
        with self.assertRaises(InvalidRequest):
            await self.poker.join(room, "short", "Chloé")
        with self.assertRaises(InvalidRequest):
            await self.poker.create_room("short", "Alice")

    async def test_participants_are_capped(self):
        room = await self.room()
        await self.poker.join(room, self.chloe, "Chloé")
        await self.poker.join(room, secret(), "Dan")
        with self.assertRaisesRegex(InvalidRequest, "pleine"):
            await self.poker.join(room, secret(), "Eve")

    async def test_a_locked_room_refuses_newcomers_not_members(self):
        room = await self.room()
        with self.assertRaisesRegex(Forbidden, "animateur"):
            await self.poker.lock(room, self.bob, True)
        await self.poker.lock(room, self.alice, True)
        with self.assertRaisesRegex(Forbidden, "verrouillée"):
            await self.poker.join(room, self.chloe, "Chloé")
        self.assertEqual(len((await self.poker.join(room, self.bob, "Bob"))["participants"]), 2)
        await self.poker.lock(room, self.alice, False)
        await self.poker.join(room, self.chloe, "Chloé")


class TestRename(Room):

    async def test_a_participant_renames_and_keeps_host_and_vote(self):
        room = await self.room()
        await self.poker.next_task(room, self.alice, "KP-1")
        await self.poker.vote(room, self.alice, "5")
        answer = await self.poker.rename(room, self.alice, "  Alicia ")
        self.assertEqual([p["nickname"] for p in answer["participants"]], ["Alicia", "Bob"])
        self.assertEqual(answer["host"], answer["me"])  # still the host
        self.assertTrue(answer["participants"][0]["voted"])  # its vote is kept
        self.assertEqual(self.publisher.published[-1][1]["participants"][0]["nickname"], "Alicia")
        with self.assertRaisesRegex(Forbidden, "déjà pris"):
            await self.poker.join(room, self.chloe, "alicia")  # the new name is the one taken
        await self.poker.join(room, self.chloe, "Alice")  # the old one is free again

    async def test_taken_by_another_is_forbidden_unchanged_or_case_is_fine(self):
        room = await self.room()
        with self.assertRaisesRegex(Forbidden, "déjà pris"):
            await self.poker.rename(room, self.bob, " ALICE ")
        self.assertEqual((await self.poker.rename(room, self.bob, "Bob"))["participants"][1]["nickname"], "Bob")  # no-op
        self.assertEqual((await self.poker.rename(room, self.bob, "BOB"))["participants"][1]["nickname"], "BOB")

    async def test_invalid_or_stranger_is_refused(self):
        room = await self.room()
        for bad in ("", "<b>x</b>", "x" * 25):
            with self.assertRaises(InvalidRequest):
                await self.poker.rename(room, self.bob, bad)
        with self.assertRaises(Forbidden):
            await self.poker.rename(room, self.chloe, "Chloé")  # never joined


class TestAvatars(Room):

    async def test_default_chosen_and_state(self):
        answer = await self.poker.create_room(self.alice, "Alice")
        self.assertEqual(answer["participants"][0]["avatar"], default_avatar("Alice"))
        room = answer["room"]
        joined = await self.poker.join(room, self.bob, "Bob", AVATARS[2])
        self.assertEqual([p["avatar"] for p in joined["participants"]], [default_avatar("Alice"), AVATARS[2]])
        again = await self.poker.join(room, self.bob, "Bob")  # rejoining without one keeps it
        self.assertEqual(again["participants"][1]["avatar"], AVATARS[2])
        created = await self.poker.create_room(self.chloe, "Chloé", AVATARS[7])
        self.assertEqual(created["participants"][0]["avatar"], AVATARS[7])

    async def test_set_avatar_is_own_only_and_validated(self):
        room = await self.room()
        answer = await self.poker.set_avatar(room, self.bob, AVATARS[4])
        self.assertEqual([p["avatar"] for p in answer["participants"]], [default_avatar("Alice"), AVATARS[4]])
        self.assertEqual(self.publisher.published[-1][1]["participants"][1]["avatar"], AVATARS[4])
        for bad in ("", "x", "🇫🇷"):
            with self.assertRaisesRegex(InvalidRequest, "Avatar inconnu"):
                await self.poker.set_avatar(room, self.bob, bad)
        with self.assertRaisesRegex(InvalidRequest, "Avatar inconnu"):
            await self.poker.join(room, self.chloe, "Chloé", "x")
        with self.assertRaises(Forbidden):
            await self.poker.set_avatar(room, self.chloe, AVATARS[0])  # never joined: nobody else's to change


class TestVoting(Room):

    async def test_votes_stay_hidden_until_revealed(self):
        room = await self.room()
        with self.assertRaisesRegex(InvalidRequest, "Aucun vote"):
            await self.poker.vote(room, self.bob, "3")
        await self.poker.next_task(room, self.alice, "#101")
        await self.poker.vote(room, self.alice, "3")
        state = await self.poker.vote(room, self.bob, "8")
        self.assertEqual([(p["voted"], p["card"]) for p in state["participants"]], [(True, None), (True, None)])
        self.assertIsNone(state["results"])
        for topic, published in self.publisher.published:
            self.assertEqual(topic, room_topic(room))
            self.assertTrue(all(p["card"] is None for p in published["participants"]))
        with self.assertRaisesRegex(Forbidden, "animateur"):
            await self.poker.reveal(room, self.bob)
        state = await self.poker.reveal(room, self.alice)
        self.assertEqual([p["card"] for p in state["participants"]], ["3", "8"])
        self.assertEqual((state["results"]["average"], state["results"]["nearest"]), (5.5, "5"))
        self.assertEqual(state["task"], {"id": state["task"]["id"], "number": "101", "revealed": True, "final": "5"})
        self.assertEqual(self.publisher.published[-1][1]["results"]["nearest"], "5")  # everyone told

    async def test_a_card_changes_after_the_reveal_and_the_results_follow(self):
        room = await self.room()
        await self.poker.next_task(room, self.alice, "101")
        await self.poker.vote(room, self.alice, "3")
        await self.poker.vote(room, self.bob, "8")
        await self.poker.reveal(room, self.alice)
        state = await self.poker.vote(room, self.bob, "3")   # Bob changes his mind once he sees the cards
        self.assertEqual([p["card"] for p in state["participants"]], ["3", "3"])
        self.assertTrue(state["results"]["consensus"])
        self.assertEqual(state["task"]["final"], "3")   # the computed estimate follows
        self.assertEqual(self.publisher.published[-1][1]["results"]["nearest"], "3")   # everyone told
        await self.poker.set_final(room, self.alice, "5")   # the host's own pick ...
        state = await self.poker.vote(room, self.bob, "13")
        self.assertEqual(state["task"]["final"], "5")   # ... stays
        self.assertTrue(state["task"]["revealed"])

    async def test_cards_withdraw_revote_final_and_recap(self):
        room = await self.room()
        await self.poker.next_task(room, self.alice, "7")
        with self.assertRaisesRegex(InvalidRequest, "Carte"):
            await self.poker.vote(room, self.bob, "4")
        await self.poker.vote(room, self.bob, "5")
        state = await self.poker.vote(room, self.bob, "")
        self.assertFalse(state["participants"][1]["voted"])
        await self.poker.vote(room, self.bob, "13")
        await self.poker.reveal(room, self.alice)
        state = await self.poker.revote(room, self.alice)
        self.assertEqual(self.manager.of(VOTE_ITEM), [])
        self.assertFalse(state["task"]["revealed"])
        await self.poker.vote(room, self.bob, "2")
        await self.poker.reveal(room, self.alice)
        with self.assertRaises(Forbidden):
            await self.poker.set_final(room, self.bob, "3")
        state = await self.poker.set_final(room, self.alice, "3")
        self.assertEqual(state["tasks"], [{"number": "7", "final": "3"}])
        state = await self.poker.next_task(room, self.alice, "8")
        self.assertEqual((state["task"]["number"], state["task"]["revealed"]), ("8", False))
        self.assertEqual(state["tasks"], [{"number": "7", "final": "3"}])

    async def test_tasks_are_numbers_or_keys_and_capped(self):
        room = await self.room()
        for wrong in ("KP-", "", "1" * 33, "KP 111"):
            with self.assertRaisesRegex(InvalidRequest, "Numéro"):
                await self.poker.next_task(room, self.alice, wrong)
        with self.assertRaises(Forbidden):
            await self.poker.next_task(room, self.bob, "1")
        for number in ("1", "2", "3"):
            await self.poker.next_task(room, self.alice, number)
        with self.assertRaisesRegex(InvalidRequest, "Limite"):
            await self.poker.next_task(room, self.alice, "4")
        self.assertEqual(len(self.manager.of(TASK_ITEM)), 1)  # those never revealed are dropped

    async def test_the_host_removes_a_participant_and_their_vote(self):
        room = await self.room()
        await self.poker.next_task(room, self.alice, "1")
        await self.poker.vote(room, self.bob, "5")
        bob = next(p["id"] for p in (await self.poker.state(room, self.bob))["participants"] if p["nickname"] == "Bob")
        with self.assertRaises(Forbidden):
            await self.poker.remove(room, self.bob, bob)
        host = (await self.poker.state(room, self.alice))["me"]
        with self.assertRaises(InvalidRequest):
            await self.poker.remove(room, self.alice, host)
        state = await self.poker.remove(room, self.alice, bob)
        self.assertEqual([p["nickname"] for p in state["participants"]], ["Alice"])
        self.assertEqual(self.manager.of(VOTE_ITEM), [])
        self.assertIsNone((await self.poker.state(room, self.bob))["me"])


class TestExpiry(Room):

    async def test_inactive_rooms_are_purged(self):
        old = await self.room()
        self.manager.items[ROOM_ITEM][old]["active_at"] = time.time() - 91 * 86400
        recent = (await self.poker.create_room(self.chloe, "Chloé"))["room"]  # a creation purges
        self.assertEqual(set(self.manager.items[ROOM_ITEM]), {recent})
        with self.assertRaises(NotFound):
            await self.poker.state(old, self.alice)

    def test_a_purged_room_takes_its_records_along(self):
        descriptor = yaml.safe_load(resources.files("ycappuccino.planningpoker").joinpath("ycappuccino_app.yml")
                                    .read_text(encoding="utf-8"))
        cascades = descriptor["components"]["PolymorphicCascade"]["cascades"]
        self.assertEqual({(c["item"], c["by"], c["of"]) for c in cascades},
                         {(item, "room", ROOM_ITEM) for item in (PARTICIPANT_ITEM, TASK_ITEM, VOTE_ITEM)})


class TestHostHandover(Room):
    """host_absent_seconds=120: a host unseen longer hands the room to the earliest-joined participant still present"""

    def setUp(self):
        super().setUp()
        self.now = 1_000_000.0
        patch = mock.patch("time.time", lambda: self.now)
        patch.start()
        self.addCleanup(patch.stop)
        self.poker = PlanningPoker(self.manager, NoLimits(), host_absent_seconds=120)

    async def room3(self) -> str:
        room = await self.room()  # Alice hosts, Bob joined
        self.now += 10
        await self.poker.join(room, self.chloe, "Chloé")
        return room

    async def host_of(self, room, who) -> str:
        state = await self.poker.ping(room, who)
        return next(p["nickname"] for p in state["participants"] if p["id"] == state["host"])

    async def test_no_handover_before_two_minutes(self):
        room = await self.room3()
        self.now += 110  # exactly 120 s since Alice was last seen
        self.assertEqual(await self.host_of(room, self.bob), "Alice")

    async def test_handover_after_two_minutes_to_the_next_joined(self):
        room = await self.room3()
        self.now += 121
        await self.poker.ping(room, self.chloe)  # Chloé present, Bob (joined first) absent too
        self.now += 1
        self.assertEqual(await self.host_of(room, self.chloe), "Chloé")
        self.assertEqual(self.publisher.published[-1][1]["host"], self.manager.of(ROOM_ITEM)[0]["host"])

    async def test_the_next_joined_still_present_is_chosen(self):
        room = await self.room3()
        for _ in range(3):
            self.now += 60
            await self.poker.ping(room, self.bob)
            await self.poker.ping(room, self.chloe)
        self.now += 130
        state = await self.poker.ping(room, self.chloe)
        self.assertEqual(next(p["nickname"] for p in state["participants"] if p["id"] == state["host"]), "Chloé")
        state = await self.poker.ping(room, self.bob)  # Bob joined first but was absent the same time: not chosen
        self.assertEqual(next(p["nickname"] for p in state["participants"] if p["id"] == state["host"]), "Chloé")

    async def test_the_earliest_present_wins(self):
        room = await self.room3()
        self.now += 100
        await self.poker.ping(room, self.chloe)
        await self.poker.ping(room, self.bob)
        self.now += 100
        self.assertEqual(await self.host_of(room, self.chloe), "Bob")

    async def test_the_old_host_returns_as_a_participant(self):
        room = await self.room3()
        self.now += 200
        await self.poker.ping(room, self.bob)
        self.assertEqual(await self.host_of(room, self.bob), "Bob")
        state = await self.poker.join(room, self.alice, "Alice")
        self.assertNotEqual(state["host"], state["me"])
        with self.assertRaisesRegex(Forbidden, "animateur"):
            await self.poker.lock(room, self.alice, True)

    async def test_the_returning_host_keeps_the_room_if_nobody_checked(self):
        room = await self.room3()
        self.now += 500  # everyone absent, nobody called: the host's own call counts first
        state = await self.poker.ping(room, self.alice)
        self.assertEqual(state["host"], state["me"])

    async def test_host_actions_are_enforced_for_the_new_host(self):
        room = await self.room3()
        await self.poker.next_task(room, self.alice, "1")
        self.now += 200
        await self.poker.vote(room, self.bob, "5")  # Bob's call hands the room over
        with self.assertRaisesRegex(Forbidden, "animateur"):
            await self.poker.reveal(room, self.alice)  # ... the old host (back) is a participant
        with self.assertRaisesRegex(Forbidden, "animateur"):
            await self.poker.reveal(room, self.chloe)
        state = await self.poker.reveal(room, self.bob)
        self.assertTrue(state["task"]["revealed"])
        await self.poker.lock(room, self.bob, True)

    async def test_the_call_that_hands_over_may_itself_be_a_host_action(self):
        room = await self.room3()
        await self.poker.next_task(room, self.alice, "1")
        self.now += 200
        state = await self.poker.reveal(room, self.bob)  # Bob's first call after Alice's absence
        self.assertTrue(state["task"]["revealed"])

    async def test_a_lone_absent_host_keeps_the_room(self):
        answer = await self.poker.create_room(self.alice, "Alice")
        self.now += 1000
        state = await self.poker.state(answer["room"], self.alice)
        self.assertEqual(state["host"], state["me"])


class TestRateLimits(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.manager = MemoryManager()
        self.limits = RateLimits({"create": [2, 3600], "join_failure": [3, 600], "action": [50, 60]})
        self.poker = PlanningPoker(self.manager, self.limits)

    async def test_room_creation_is_limited_per_address(self):
        VISITOR_ADDRESS.set("203.0.113.1")
        await self.poker.create_room(secret(), "A")
        await self.poker.create_room(secret(), "A")
        with self.assertRaisesRegex(InvalidRequest, "Trop de tentatives"):
            await self.poker.create_room(secret(), "A")
        VISITOR_ADDRESS.set("203.0.113.2")
        await self.poker.create_room(secret(), "A")

    async def test_guessing_rooms_is_throttled_per_address(self):
        VISITOR_ADDRESS.set("198.51.100.7")
        room = (await self.poker.create_room(secret(), "A"))["room"]
        VISITOR_ADDRESS.set("198.51.100.8")
        for _ in range(3):
            with self.assertRaises(NotFound):
                await self.poker.join(secrets.token_urlsafe(24), secret(), "Guess")
        with self.assertRaisesRegex(InvalidRequest, "Trop de tentatives"):
            await self.poker.join(room, secret(), "Guess")  # even a real one, until the window slides
        VISITOR_ADDRESS.set("198.51.100.9")
        await self.poker.join(room, secret(), "Other")

    async def test_actions_are_limited(self):
        VISITOR_ADDRESS.set("192.0.2.5")
        limits = RateLimits({"action": [3, 60]})
        poker = PlanningPoker(self.manager, limits)
        host = secret()
        room = (await poker.create_room(host, "A"))["room"]
        for _ in range(3):
            await poker.lock(room, host, True)
        with self.assertRaisesRegex(InvalidRequest, "Trop de tentatives"):
            await poker.lock(room, host, False)


if __name__ == "__main__":
    unittest.main()
