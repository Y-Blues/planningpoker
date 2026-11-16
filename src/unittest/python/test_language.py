"""The page's language: the browser's (English for en*, else French), the header's switch over it, kept by the browser;
every text from strings.py, the server's refusals (coded messages) too."""

import asyncio
import re
import unittest
import urllib.parse
from importlib import resources

from ycappuccino.api.endpoints_storage import Forbidden
from ycappuccino.api.messages import coded
from ycappuccino.ui.strings import DEFAULT_STRINGS

from ycappuccino.planningpoker.deck import format_average
from ycappuccino.planningpoker.page import view
from ycappuccino.planningpoker.strings import BOOKMARKLET_TEXTS, LANGUAGE_PREFERENCE
from ycappuccino.ui_web.testing import FakeDom

from ycappuccino.planningpoker.page.poker_page import PokerPage
from test_page import ROOM, FakeCrud, FakePage, FakePoker, FakeSubscriptions, Page, seeded, state, texts

POKER_STRINGS = {record["key"]: record["text"] for record in seeded("ycappuccino.planningpoker", "seed/translations.json")}


def locale(lang):
    return texts().with_language(lang)


class TestChoice(Page):

    async def test_an_english_browser_gets_english(self):
        await self.open(languages=("en-GB", "fr"))
        self.assertEqual(self.page._ui["enter"].text, "Create a room")
        self.assertEqual(self.dom.lang, "en")
        self.assertIn("Powered by", "".join(child.text for child in self.find("span")))

    async def test_any_other_browser_gets_french(self):
        for languages in (("de-DE",), ("fr-CA", "en"), ()):
            await self.open(languages=languages)
            self.assertEqual(self.page._ui["enter"].text, "Créer une salle", languages)
            self.assertEqual(self.dom.lang, "fr")

    async def test_the_switch_overrides_the_browser_and_is_kept(self):
        await self.open(languages=("fr-FR",))
        self.page._ui["nickname"].value = "Alice"
        self.page._ui["language"].value = "en"
        await self.dom.change(self.page._ui["language"])
        self.assertEqual(self.dom.preferences[LANGUAGE_PREFERENCE], "en")
        self.assertEqual(self.page._ui["enter"].text, "Create a room")
        self.assertEqual(self.page._ui["nickname"].value, "Alice")   # relabelled, not rebuilt
        self.assertEqual(self.page._ui["nickname"].attrs["placeholder"], "e.g. Sam")
        self.assertEqual(self.dom.lang, "en")
        await self.open(languages=("fr-FR",), preferences={LANGUAGE_PREFERENCE: "en"})
        self.assertEqual(self.page._ui["enter"].text, "Create a room")
        await self.open(languages=("en-US",), preferences={LANGUAGE_PREFERENCE: "auto"})
        self.assertEqual(self.page._ui["enter"].text, "Create a room")

    async def test_a_refusal_is_said_in_the_language_and_again_after_a_switch(self):
        await self.open("/#" + ROOM, answer={**state(), "me": None}, languages=("en-US",))
        self.poker.error = Forbidden(coded("poker.error.nickname_taken"))
        await self.dom.click(self.page._ui["enter"])
        self.assertEqual(self.page._ui["error"].text, "This nickname is already taken in this room.")
        self.page._ui["language"].value = "fr"
        await self.dom.change(self.page._ui["language"])
        self.assertEqual(self.page._ui["error"].text, "Ce pseudo est déjà pris dans cette salle.")

    async def test_the_room_in_english(self):
        await self.open("/#" + ROOM, answer={**state(revealed=True), "me": "a"}, languages=("en",))
        stats = [element.text for element in self.find("dt")]
        self.assertEqual(stats, ["Average", "Closest card", "Min", "Max", "Votes"])
        self.assertEqual(self.find("dd")[0].text, "5.5")
        self.assertEqual([cell.text for cell in self.find("th")], ["Task", "Estimate"])
        self.assertIn("· host", self.page._ui["me"].text)
        self.assertEqual(self.page._ui["task_title"].text, "Task 12")
        href = urllib.parse.unquote(self.page._ui["bookmarklet"].attrs["href"])
        self.assertIn("open a Jira page first", href)
        self.assertNotIn("__TEXTS__", href)


class TestTutorial(Page):

    async def test_the_jira_how_to_opens_from_the_import_area_closes_and_follows_the_language(self):
        await self.open("/#" + ROOM, answer={**state(), "me": "a"})
        drawer = self.page._tutorial
        self.assertFalse(drawer.is_open)
        await self.dom.click(self.page._ui["tutorial_open"])
        self.assertTrue(drawer.is_open)
        titles = [element.text for element in self.find(".yc-step-title")]
        self.assertEqual(titles[:5], ["Affichez la barre de favoris", "Glissez ce bouton dans la barre de favoris", "Ouvrez Jira",
                                      "Cliquez sur le favori", "Confirmez, puis jouez"])
        self.assertEqual([element.text for element in self.find(".yc-step-number")], ["1", "2", "3", "4", "5"])
        self.assertEqual(len(self.find(".yc-step-figure")), 5)
        self.assertEqual([key.text for key in self.find(".pp-ill-key")], ["Ctrl / ⌘", "Maj", "B"])
        link = self.page._ui["bookmarklet"]
        self.assertTrue(link.attrs["href"].startswith("javascript:"))
        await self.dom.click(self.page._ui["bookmarklet_copy"])
        self.assertEqual(await self.dom.read_clipboard_text(), link.attrs["href"])
        self.assertEqual(self.page._ui["bookmarklet_copy"].text, "Favori copié ✓")
        self.page._ui["language"].value = "en"
        await self.dom.change(self.page._ui["language"])
        self.assertEqual(self.find(".yc-step-title")[0].text, "Show the bookmarks bar")
        self.assertEqual([key.text for key in self.find(".pp-ill-key")], ["Ctrl / ⌘", "Shift", "B"])
        self.assertEqual(self.find(".yc-drawer-title")[0].text, "Import from Jira, step by step")
        self.assertIn("open a Jira page first", urllib.parse.unquote(link.attrs["href"]))
        await self.dom.escape()
        self.assertFalse(drawer.is_open)
        self.assertIs(self.dom.focused, self.page._ui["tutorial_open"])


class TestStoredTexts(Page):

    async def test_the_texts_and_languages_are_read_from_the_storage_as_a_visitor(self):
        await self.open()
        asked = {item: params for item, params in self.crud.asked}
        self.assertEqual(set(asked), {"language", "translation"})
        self.assertTrue(asked["translation"].get("inherit"))   # ycappuccino.ui.i18n: the organization's, then the platform's
        self.assertEqual([option.text for option in self.page._ui["language"].children], ["Auto", "Français", "English"])
        label = self.find(".yc-language")[0]
        self.assertIs(label.children[1], self.page._ui["language"])
        self.assertEqual((label.tag, label.attrs["class"], label.children[0].text), ("label", "yc-language", "🌐"))

    async def test_the_items_are_the_page_s_properties(self):
        crud = FakeCrud()
        crud.items = {"site_language": crud.items["language"], "site_translation": crud.items["translation"]}
        dom = FakeDom("/")
        dom.browser_languages = ["en"]
        page = PokerPage(FakePage(dom), FakePoker(), FakeSubscriptions(), crud,
                         language_item="site_language", translation_item="site_translation")
        await page.start()
        await page._loading
        self.assertEqual({item for item, _ in crud.asked}, {"site_language", "site_translation"})
        self.assertEqual(page._ui["enter"].text, "Create a room")

    async def test_the_document_s_language_is_set_before_the_texts_are_read(self):
        crud = FakeCrud()
        released = asyncio.Event()
        read = crud.get_many

        async def slow(item, params, subject=None):
            await released.wait()
            return await read(item, params, subject)

        crud.get_many = slow
        dom = FakeDom("/")
        dom.browser_languages = ["en-GB"]
        starting = asyncio.ensure_future(PokerPage(FakePage(dom), FakePoker(), FakeSubscriptions(), crud).start())
        await asyncio.sleep(0)
        self.assertEqual(dom.lang, "en")   # the storage not answered yet
        released.set()
        await starting

    async def test_a_text_edited_in_the_storage_is_the_one_shown(self):
        crud = FakeCrud()
        crud.items["translation"] = [{"key": "poker.create", "text": {"fr": "Ouvrir une salle", "en": "Open a room"}}] + \
            crud.items["translation"]   # the nearest organization's record first (the inherited read's order)
        await self.open(crud=crud)
        self.assertEqual(self.page._ui["enter"].text, "Ouvrir une salle")

    async def test_unreadable_texts_are_said_never_a_page_of_keys(self):
        crud = FakeCrud({"language": [], "translation": []})   # refused, or not seeded
        with self.assertLogs("ycappuccino.planningpoker.page.poker_page", "ERROR"):
            await self.open(crud=crud)
        self.assertFalse(self.hidden("error"))
        self.assertNotIn("poker.", self.page._ui["error"].text)
        self.assertEqual(self.page._ui["enter"].text, "Créer une salle")   # the shipped texts, never a bare key


class TestStrings(unittest.TestCase):

    def test_every_key_in_french_and_english(self):
        for key, texts in POKER_STRINGS.items():
            self.assertTrue(key.startswith("poker."), key)
            self.assertTrue(texts.get("fr") and texts.get("en"), key)
            self.assertEqual(set(re.findall(r"{(\w+)}", texts["fr"])), set(re.findall(r"{(\w+)}", texts["en"])), key)
        self.assertFalse(set(POKER_STRINGS) & set(DEFAULT_STRINGS))
        records = seeded("ycappuccino.planningpoker", "seed/translations.json")
        self.assertTrue(all(record["id"] == record["key"] for record in records))   # the seed's stable id: its key

    def test_every_key_used_exists(self):
        package = resources.files("ycappuccino.planningpoker")
        sources = "".join(package.joinpath(name).read_text(encoding="utf-8") for name in
                          ("rooms.py", "rate_limits.py", "api.py", "page/poker_page.py", "page/view.py", "page/tutorial.py"))
        used = set(re.findall(r'"(poker\.[a-z_.]*[a-z_])"', sources)) | set(BOOKMARKLET_TEXTS.values())
        self.assertFalse(used - set(POKER_STRINGS))
        self.assertEqual(set(re.findall(r"TEXT\.(\w+)", package.joinpath("static/jira_bookmarklet.js").read_text())), set(BOOKMARKLET_TEXTS))

    def test_numbers_in_the_language(self):
        self.assertEqual((format_average(5.25), format_average(5.25, "en"), format_average(8.0, "en")), ("5,2", "5.2", "8"))
        self.assertEqual(view.status(state(me_votes=True), "b", locale("en").t), "2 of 2 voted")
        self.assertEqual(locale("en").t(coded("poker.error.full", max=12)), "The room is full (12 participants).")


if __name__ == "__main__":
    unittest.main()
