import unittest

from ycappuccino.ui_web.navigation import Navigator
from ycappuccino.ui_web.testing import FakeDom, FakeElement

from ycappuccino.api.endpoints_storage import Forbidden, NotFound
from ycappuccino.planningpoker.api import NOT_FOUND, room_topic
from ycappuccino.planningpoker.deck import AVATARS
from ycappuccino.planningpoker.page import view
from ycappuccino.planningpoker.page.poker_page import AVATAR_KEY, SECRET_KEY, PokerPage

ROOM = "R" * 32


def state(me_votes=False, revealed=False, host="a", task=True, people=("a", "b")):
    cards = {"a": "3", "b": "8"}
    return {
        "room": ROOM, "stamp": 1, "host": host, "locked": False,
        "participants": [{"id": p, "nickname": p.upper(), "avatar": "🦊" if p == "a" else "🐼", "voted": me_votes, "card": cards[p] if revealed else None}
                         for p in people],
        "task": {"id": "t", "number": "12", "revealed": revealed, "final": "8" if revealed else ""} if task else None,
        "results": {"votes": 2, "counts": {"3": 1, "8": 1}, "consensus": False, "average": 5.5, "nearest": "8",
                    "min": "3", "max": "8"} if revealed else None,
        "tasks": [{"number": "12", "final": "8"}] if revealed else [],
    }


class FakePoker:
    def __init__(self):
        self.calls = []
        self.answer = None
        self.error = None

    def __getattr__(self, name):
        async def call(*args):
            self.calls.append((name, args))
            if self.error is not None:
                raise self.error
            return self.answer
        return call


class FakeSubscriptions:
    def __init__(self):
        self.topics = []

    async def subscribe(self, topic):
        self.topics.append(topic)

    async def unsubscribe(self, topic):
        self.topics.remove(topic)


class FakePage:
    def __init__(self, dom):
        self._navigator = Navigator(dom, FakeElement("div"))

    def navigator(self):
        return self._navigator


class Page(unittest.IsolatedAsyncioTestCase):

    async def open(self, location="/", answer=None, preferences=None):
        self.dom = FakeDom(location)
        self.dom.preferences.update(preferences or {})
        self.poker = FakePoker()
        self.poker.answer = answer
        self.subscriptions = FakeSubscriptions()
        self.page = PokerPage(FakePage(self.dom), self.poker, self.subscriptions)
        await self.page.start()
        await self.page._loading
        return self.page

    def find(self, selector):
        return self.dom.query_all(self.page._page.navigator().mount, selector)

    def hidden(self, key):
        return "hidden" in self.page._ui[key].attrs


class TestIdentity(Page):

    async def test_a_strong_secret_is_drawn_once_and_kept(self):
        await self.open()
        secret = self.dom.preferences[SECRET_KEY]
        self.assertGreaterEqual(len(secret), 43)
        await self.open(preferences={SECRET_KEY: secret})
        self.assertEqual(self.page._secret, secret)

    async def test_creating_a_room_puts_it_in_the_address_and_follows_it(self):
        await self.open()
        self.assertFalse(self.hidden("welcome"))
        self.assertEqual(self.page._ui["enter"].text, "Créer une salle")
        self.poker.answer = {**state(task=False), "me": "a"}
        await self.dom.type_text(self.page._ui["nickname"], "Alice")
        await self.dom.click(self.page._ui["enter"])
        self.assertEqual(self.poker.calls[-1], ("create_room", (self.page._secret, "Alice", "")))
        self.assertEqual(self.dom.location(), "/#" + ROOM)
        self.assertEqual(self.subscriptions.topics, [room_topic(ROOM)])
        self.assertTrue(self.hidden("welcome"))
        self.assertFalse(self.hidden("task_form"))  # the host picks the first task

    async def test_a_link_shows_the_room_to_join(self):
        await self.open("/#" + ROOM, answer={**state(), "me": None})
        self.assertEqual(self.page._ui["enter"].text, "Rejoindre")
        self.assertEqual(self.subscriptions.topics, [room_topic(ROOM)])
        self.poker.error = Forbidden("Ce pseudo est déjà pris dans cette salle.")
        await self.dom.click(self.page._ui["enter"])
        self.assertEqual(self.page._ui["error"].text, "Ce pseudo est déjà pris dans cette salle.")

    async def test_an_unknown_room_says_so(self):
        page = await self.open("/#" + "x" * 3)
        self.assertEqual(page._ui["error"].text, NOT_FOUND)
        self.poker.error = NotFound(NOT_FOUND)
        await page.open_room("Z" * 32)
        self.assertEqual(page._ui["error"].text, NOT_FOUND)
        self.assertEqual(self.subscriptions.topics, [])


class TestTable(Page):

    async def test_the_heartbeat_pings_the_room_and_shows_a_new_host(self):
        import asyncio
        from unittest import mock
        page = await self.open(f"/#{ROOM}", answer={**state(host="a"), "me": "b"})
        self.assertFalse(view.is_host(page._state, "b"))
        self.poker.answer = {**state(host="b"), "stamp": 2, "me": "b"}
        with mock.patch("ycappuccino.planningpoker.page.poker_page.HEARTBEAT_SECONDS", 0.01):
            page._beating.cancel()
            page._beating = asyncio.ensure_future(page._heartbeat())
            await asyncio.sleep(0.1)
        self.assertIn(("ping", (ROOM, page._secret)), self.poker.calls)
        self.assertTrue(view.is_host(page._state, "b"))

    async def test_votes_hidden_then_revealed(self):
        await self.open("/#" + ROOM, answer={**state(me_votes=True), "me": "b"})
        faces = [card.attrs["class"] for card in self.find(".pp-card")]
        self.assertEqual(faces, ["pp-card is-down", "pp-card is-down"])
        self.assertEqual(self.find(".pp-reveal"), [])  # b is not the host
        await self.page.on_message(room_topic(ROOM), {**state(revealed=True), "stamp": 2})
        self.assertEqual(sorted(card.text for card in self.find(".pp-card.is-up")), ["3", "8"])
        self.assertTrue(not self.hidden("deck") and not self.hidden("results"))   # the hand stays: a card may change after the reveal
        await self.page.on_message(room_topic(ROOM), {**state(), "stamp": 1})  # an older state: ignored
        self.assertEqual(len(self.find(".pp-card.is-up")), 2)

    async def test_the_host_reveals_and_removes(self):
        await self.open("/#" + ROOM, answer={**state(me_votes=True), "me": "a"})
        await self.dom.click(self.find(".pp-reveal")[0])
        self.assertEqual(self.poker.calls[-1][0], "reveal")
        await self.dom.click(self.find(".pp-remove")[0])
        self.assertEqual(self.poker.calls[-1], ("remove", (ROOM, self.page._secret, "b")))

    async def test_voting_and_withdrawing(self):
        await self.open("/#" + ROOM, answer={**state(), "me": "b"})
        five = next(card for card in self.find(".pp-deck-card") if card.text == "5")
        self.poker.answer = {**state(me_votes=True), "stamp": 2, "me": "b"}
        await self.dom.click(five)
        self.assertEqual(self.poker.calls[-1], ("vote", (ROOM, self.page._secret, "5")))
        five = next(card for card in self.find(".pp-deck-card") if card.text == "5")
        self.assertIn("is-selected", five.attrs["class"])
        self.poker.answer = {**state(), "stamp": 3, "me": "b"}
        await self.dom.click(five)
        self.assertEqual(self.poker.calls[-1], ("vote", (ROOM, self.page._secret, "")))

    async def test_a_removed_participant_is_told(self):
        await self.open("/#" + ROOM, answer={**state(), "me": "b"})
        await self.page.on_message(room_topic(ROOM), {**state(people=("a",)), "stamp": 2})
        self.assertIn("retiré", self.page._ui["error"].text)
        self.assertFalse(self.hidden("welcome"))


class TestAvatarAndFooter(Page):

    async def test_the_footer_credits_ipopo_and_ycappuccino(self):
        await self.open()
        links = self.find("a")
        self.assertEqual([link.text for link in links], ["iPOPO", "YCappuccino"])
        for link in links:
            self.assertEqual(link.attrs["target"], "_blank")
            self.assertEqual(link.attrs["rel"], "noopener")
            self.assertTrue(link.attrs["href"].startswith("https://"))

    async def test_the_join_form_picks_keeps_and_sends_an_avatar(self):
        await self.open()
        choices = self.dom.query_all(self.page._ui["welcome_picker"], ".pp-avatar-choice")
        self.assertEqual(len(choices), len(AVATARS))
        self.assertTrue(all(c.attrs["aria-label"] and c.attrs["aria-pressed"] == "false" for c in choices))
        await self.dom.click(choices[3])
        self.assertEqual(self.dom.preferences[AVATAR_KEY], AVATARS[3])
        self.assertEqual(self.dom.query_all(self.page._ui["welcome_picker"], ".pp-avatar-choice")[3].attrs["aria-pressed"], "true")
        self.poker.answer = {**state(task=False), "me": "a"}
        await self.dom.type_text(self.page._ui["nickname"], "Alice")
        await self.dom.click(self.page._ui["enter"])
        self.assertEqual(self.poker.calls[-1], ("create_room", (self.page._secret, "Alice", AVATARS[3])))

    async def test_the_last_choice_is_preselected(self):
        await self.open(preferences={AVATAR_KEY: AVATARS[5]})
        self.assertEqual(self.dom.query_all(self.page._ui["welcome_picker"], ".pp-avatar-choice")[5].attrs["aria-pressed"], "true")

    async def test_the_room_shows_avatars_and_my_own_reopens_the_picker(self):
        await self.open("/#" + ROOM, answer={**state(), "me": "a"})
        self.assertEqual(sorted(seat.text for seat in self.find(".pp-avatar")), ["🐼", "🦊"])
        self.assertEqual(len(self.find("button.pp-avatar")), 1)  # only mine
        self.assertTrue(self.hidden("picker"))
        await self.dom.click(self.find("button.pp-avatar")[0])
        self.assertFalse(self.hidden("picker"))
        self.poker.answer = {**state(), "stamp": 2, "me": "a"}
        await self.dom.click(self.dom.query_all(self.page._ui["picker"], ".pp-avatar-choice")[1])
        self.assertEqual(self.poker.calls[-1], ("set_avatar", (ROOM, self.page._secret, AVATARS[1])))
        self.assertTrue(self.hidden("picker"))
        self.assertEqual(self.dom.preferences[AVATAR_KEY], AVATARS[1])


class TestView(unittest.TestCase):

    def test_status_and_recap(self):
        self.assertEqual(view.status(state(task=False), "a"), "Choisissez la première tâche.")
        self.assertEqual(view.status(state(me_votes=True), "b"), "2 votes sur 2")
        self.assertEqual(view.recap(state(revealed=True)), ([("12", "8")], "8"))
        self.assertEqual(view.results(state(revealed=True))[0], ("Moyenne", "5,5"))

    def test_moments_play_once(self):
        first, snap = view.moments(None, state(), "a", "")
        self.assertTrue(first["deal"])
        self.assertEqual(first["joined"], {"a", "b"})
        again, snap = view.moments(snap, state(), "a", "")
        self.assertFalse(again["deal"] or again["joined"] or again["flip"])
        voted, snap = view.moments(snap, state(me_votes=True), "a", "3")
        self.assertEqual(voted["voted"], {"a", "b"})
        self.assertTrue(voted["picked"])
        shown, snap = view.moments(snap, {**state(revealed=True, me_votes=True)}, "a", "3")
        self.assertTrue(shown["flip"] and not shown["celebrate"] and not shown["deal"])
        revote, _ = view.moments(snap, state(), "a", "")
        self.assertTrue(revote["deal"] and not revote["flip"])
        agreed = state(revealed=True, me_votes=True)
        agreed["results"] = {**agreed["results"], "consensus": True}
        party, _ = view.moments(view.moments(None, state(me_votes=True), "a", "")[1], agreed, "a", "")
        self.assertTrue(party["celebrate"])


class TestMoments(Page):

    async def test_the_reveal_keeps_playing_when_the_same_state_comes_twice(self):
        await self.open("/#" + ROOM, answer={**state(me_votes=True), "me": "a"})
        revealed = {**state(revealed=True, me_votes=True), "stamp": 2}
        await self.page.on_message(room_topic(ROOM), revealed)
        self.assertTrue(self.find(".pp-countdown"))
        await self.page.on_message(room_topic(ROOM), revealed)  # the RPC answer, then the topic's message
        self.assertTrue(self.find(".pp-countdown") and all("is-flip" in c.attrs["class"] for c in self.find(".pp-card")))
        await self.page.on_message(room_topic(ROOM), {**revealed, "stamp": 3})  # same content, a newer stamp
        self.assertTrue(self.find(".pp-countdown"))
        await self.page.on_message(room_topic(ROOM), {**revealed, "stamp": 4, "task": {**revealed["task"], "final": "3"}})
        self.assertFalse(self.find(".pp-countdown"))
