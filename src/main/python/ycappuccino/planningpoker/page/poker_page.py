"""PokerPage: the planning poker's page, in the languages and with the texts of the storage (the `language` and
`translation` items, read over ICrud as the Y.Blues site reads them: strings.load): the browser's language, or the one
picked in the header's ui_web LanguageSwitch, kept by the browser. Its room is the address's hash (`#<room id>`: never sent to the server
nor kept in its logs); its identity a secret this browser draws once and keeps (localStorage), bound by the server to the
nickname it joins with. It follows the room's topic (pubsub) and draws each state it receives; a (re)subscription asks
the state again, so nothing is missed across a reconnection. Draws through the page's DomBinding only."""

import asyncio
import logging
import time
from typing import Any, Optional

from ycappuccino.api.endpoints_storage import ICrud
from ycappuccino.api.pubsub import ISubscriber, ISubscriptionListener, ISubscriptions
from ycappuccino.ui.datasource import PagedSource
from ycappuccino.ui.errors import error_key, transport_failure
from ycappuccino.ui.i18n import Locale, built_in_locale
from ycappuccino.ui.ycappuccino_transport import CrudDataSource
from ycappuccino.ui_web.builder import Builder
from ycappuccino.ui_web.drawer import Drawer
from ycappuccino.ui_web.language import LanguageSwitch
from ycappuccino.ui_web.page import IWebPage

from ycappuccino.planningpoker.api import NOT_FOUND, IPlanningPoker, room_topic
from ycappuccino.planningpoker.deck import AVATARS, DECK, NICKNAME_MAX, is_room_id
from ycappuccino.planningpoker.page import browser, jira, tutorial, view
from ycappuccino.planningpoker import strings
from ycappuccino.planningpoker.strings import BOOKMARKLET_TEXTS, LANGUAGE_PREFERENCE

_logger = logging.getLogger(__name__)

SECRET_KEY = "planningpoker.secret"
NICKNAME_KEY = "planningpoker.nickname"
AVATAR_KEY = "planningpoker.avatar"
IPOPO_URL = "https://github.com/tcalmant/ipopo"
YCAPPUCCINO_URL = "https://github.com/Y-Blues/core"
HEARTBEAT_SECONDS = 15  # well under the server's host_absent_seconds
MOMENT_SECONDS = 4  # the longest animation (the reveal's countdown, flips, confetti) is over by then
TEXTS_TRIES, TEXTS_WAIT = 15, 2.0  # the texts asked again while the server starts (then the built-in ones, the error said)


class PokerPage(ISubscriber, ISubscriptionListener):

    def __init__(self, page: IWebPage, poker: IPlanningPoker, subscriptions: ISubscriptions, crud: ICrud) -> None:
        self._page = page
        self._source = PagedSource(CrudDataSource(crud))
        self._poker = poker
        self._subscriptions = subscriptions
        self._dom: Any = None
        self._ui: dict = {}
        self._room: Optional[str] = None
        self._state: Optional[dict] = None
        self._me: Optional[str] = None
        self._chosen = ""  # the card this page voted on the current task
        self._secret = ""
        self._editing = False  # the profile panel (nickname, avatar) is open
        self._pick = ""  # the avatar chosen in that panel, not saved yet
        self._avatar = ""  # the avatar picked on the join form ("": by nickname)
        self._loading: Optional[asyncio.Future] = None
        self._topic: Optional[str] = None
        self._beating: Optional[asyncio.Future] = None
        self._before: Optional[dict] = None  # the last drawing's snapshot (view.moments)
        self._moments: dict = {}  # what the current drawing animates
        self._drawn: Optional[dict] = None  # the state drawn last (its stamp aside)
        self._pending: Optional[tuple[str, list]] = None  # (Jira site, tickets) received, waiting for the host's OK
        self._since = 0.0  # when the current moments started (a redraw resumes them where they are)
        self._texts: Locale = built_in_locale()   # the storage's languages and texts, every language
        self._locale: Locale = self._texts   # the same, in the language shown
        self._language: Optional[LanguageSwitch] = None
        self._b: Optional[Builder] = None  # the static texts, relabelled when the language changes
        self._error_text = ""  # the error shown, as a key or a coded message (shown again in a new language)
        self._tutorial: Optional[Drawer] = None  # the Jira import's how-to

    def t(self, key: str, **values: Any) -> str:
        """a text in the page's language"""
        return self._locale.t(key, **values)

    async def start(self) -> None:
        self._dom = self._page.navigator().dom
        self._b = Builder(self._dom, self.t)
        problem = await self._load_texts()
        self._language = LanguageSwitch(self._dom, self._texts.languages, preference=LANGUAGE_PREFERENCE,
                                        on_change=self._language_changed)
        self._locale = self._texts.with_language(self._language.effective())
        self._language.set_auto_label(self.t("ui.language_auto"))
        self._dom.set_document(self.t("poker.brand"), self._locale.language)
        self._secret = self._dom.load_preference(SECRET_KEY) or ""
        if len(self._secret) < 32:
            self._secret = browser.new_secret()
            self._dom.save_preference(SECRET_KEY, self._secret)
        saved = self._dom.load_preference(AVATAR_KEY) or ""
        self._avatar = saved if saved in AVATARS else ""
        self._build(self._page.navigator().mount)
        if problem:
            self._error(problem)
        self._dom.on_escape(self.close_profile)
        self._dom.on_navigate(lambda _url: self.open_room(self._hash()))
        self._dom.on_window_message(self.window_message)
        self._dom.post_to_opener({"type": jira.READY})   # opened by the Jira bookmarklet: it may now send its tickets
        self._loading = asyncio.ensure_future(self.open_room(self._hash()))
        self._beating = asyncio.ensure_future(self._heartbeat())

    async def _load_texts(self) -> str:
        """the storage's languages and texts ("" once read); while the server starts they are asked again, then the
        built-in texts stay and the error is named (the returned key, also logged)"""
        for attempt in range(TEXTS_TRIES):
            try:
                texts = await strings.load(self._source)
            except Exception as error:
                if not transport_failure(error) or attempt == TEXTS_TRIES - 1:
                    _logger.error("the poker's texts (language, translation) are not readable: %s", error)
                    self._texts = built_in_locale(self._dom.languages())
                    return error_key(error) or "ui.server_error"
                await asyncio.sleep(TEXTS_WAIT)
                continue
            if "poker.brand" not in texts.strings:   # refused or not seeded: never a page of bare keys without a word
                _logger.error("the poker's texts are missing from the translation item (seed planningpoker-texts)")
                self._texts = built_in_locale(self._dom.languages())
                return "ui.server_error"
            self._texts = texts
            return ""
        return "ui.server_error"

    async def _language_changed(self, language: str) -> None:
        """the page's texts in the new language, at once (nothing rebuilt: the inputs keep what is typed)"""
        self._locale = self._texts.with_language(language)
        self._dom.set_document(self.t("poker.brand"), self._locale.language)
        self._language.set_auto_label(self.t("ui.language_auto"))
        self._b.relabel()
        self._tutorial.set_title(self.t("poker.tutorial.title"), self.t("poker.close"))
        self._error(self._error_text)
        self._draw()

    async def stop(self) -> None:
        if self._loading is not None:
            self._loading.cancel()
        if self._beating is not None:
            self._beating.cancel()

    async def _heartbeat(self) -> None:
        """tells the server this participant is still here (a host unseen for long hands the room over)"""
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            if self._room and self._me is not None:
                try:
                    self._apply(await self._poker.ping(self._room, self._secret), self._me)
                except Exception:  # a dropped connection: the next beat, or the resubscription, catches up
                    _logger.debug("heartbeat failed", exc_info=True)

    # ------------------------------------------------------------------ server events

    async def on_message(self, topic: str, message: Any) -> None:
        if self._room and topic == room_topic(self._room) and isinstance(message, dict):
            self._apply(message, self._me)

    async def subscription_changed(self, topic: str, active: bool, reason: str) -> None:
        if self._room and topic == room_topic(self._room) and active:
            await self._call(self._poker.state(self._room, self._secret))  # caught up after a (re)connection

    # ------------------------------------------------------------------ actions

    async def open_room(self, room: str) -> None:
        if room == self._room and self._state is not None:
            return
        await self._follow(None)
        self._state, self._me, self._chosen, self._before = None, None, "", None
        if room and not is_room_id(room):
            self._error(NOT_FOUND)
            room = ""
        if not room:
            self._draw()
            return
        self._room = room
        if await self._call(self._poker.state(room, self._secret)) is None:
            self._room = None
            self._draw()
            return
        await self._follow(room)

    async def create(self) -> None:
        nickname = self._nickname()
        answer = await self._call(self._poker.create_room(self._secret, nickname, self._avatar))
        if answer is None:
            return
        self._room = answer["room"]
        self._dom.replace_url(self._dom.location().partition("#")[0] + "#" + self._room)
        self._draw()   # the room's link (the bookmarklet's) is known now
        await self._follow(self._room)

    async def join(self) -> None:
        await self._call(self._poker.join(self._room, self._secret, self._nickname(), self._avatar))

    async def pick_avatar(self, avatar: str) -> None:
        """the join form's choice (picking it again drops it), kept for next time"""
        self._avatar = "" if avatar == self._avatar else avatar
        self._dom.save_preference(AVATAR_KEY, self._avatar)
        self._draw_picker(self._ui["welcome_picker"], self._avatar, self.pick_avatar)

    async def toggle_profile(self) -> None:
        if self._editing:
            await self.close_profile()
            return
        mine = next((seat for seat in view.seats(self._state or {}, self._me) if seat["me"]), None)
        if mine is None:
            return
        self._error("")
        self._editing, self._pick = True, mine["avatar"]
        self._dom.set_value(self._ui["profile_name"], mine["nickname"])
        self._draw_picker(self._ui["picker"], self._pick, self.choose_avatar)
        self._show(self._ui["profile"], True)
        self._dom.set_attribute(self._ui["edit"], "aria-expanded", "true")
        self._dom.focus(self._ui["profile_name"])

    async def close_profile(self) -> None:
        if not self._editing:
            return
        self._editing = False
        self._show(self._ui["profile"], False)
        self._dom.set_attribute(self._ui["edit"], "aria-expanded", "false")
        self._dom.focus(self._ui["edit"])

    async def choose_avatar(self, avatar: str) -> None:
        self._pick = avatar
        self._draw_picker(self._ui["picker"], avatar, self.choose_avatar)

    async def save_profile(self) -> None:
        """the nickname and avatar changed in the panel are saved (the panel stays open on a refusal)"""
        name = " ".join(self._dom.get_value(self._ui["profile_name"]).split())
        mine = next((seat for seat in view.seats(self._state or {}, self._me) if seat["me"]), None)
        if mine is None:
            return
        if name != mine["nickname"] and await self._call(self._poker.rename(self._room, self._secret, name)) is None:
            return
        if self._pick and self._pick != mine["avatar"]:
            if await self._call(self._poker.set_avatar(self._room, self._secret, self._pick)) is None:
                return
            self._avatar = self._pick
            self._dom.save_preference(AVATAR_KEY, self._avatar)
        self._dom.save_preference(NICKNAME_KEY, name)
        await self.close_profile()

    async def vote(self, card: str) -> None:
        if not view.can_vote(self._state or {}, self._me):
            return
        choice = "" if card == view.my_card(self._state, self._me, self._chosen) else card
        if await self._call(self._poker.vote(self._room, self._secret, choice)) is not None:
            self._chosen = choice
            self._draw()

    async def reveal(self) -> None:
        await self._call(self._poker.reveal(self._room, self._secret))

    async def revote(self) -> None:
        await self._call(self._poker.revote(self._room, self._secret))

    async def set_final(self, card: str) -> None:
        await self._call(self._poker.set_final(self._room, self._secret, card))

    async def next_task(self) -> None:
        number = self._dom.get_value(self._ui["task_input"])
        parent = self._dom.get_value(self._ui["parent_input"])
        if await self._call(self._poker.next_task(self._room, self._secret, number, parent.strip())) is not None:
            self._dom.set_value(self._ui["task_input"], "")   # the parent stays: the next task is often its sibling

    async def play(self, number: str) -> None:
        """a queued ticket picked from the tree"""
        await self._call(self._poker.next_task(self._room, self._secret, number))

    async def window_message(self, origin: str, data: Any) -> None:
        """a Jira page (the bookmarklet) sends tickets: kept for the host to confirm; "hello" answers "ready" again"""
        if jira.site(origin) is None:
            return
        if isinstance(data, dict) and data.get("type") == jira.HELLO:
            self._dom.post_to_opener({"type": jira.READY})
            return
        found = jira.received(origin, data)
        if found is not None:
            self._pending = found
            self._draw()

    async def import_pending(self) -> None:
        if self._pending is None:
            return
        if await self._call(self._poker.import_tasks(self._room, self._secret, self._pending[1])) is not None:
            self._pending = None
            self._draw()

    async def drop_pending(self) -> None:
        self._pending = None
        self._draw()

    async def remove(self, participant: str) -> None:
        await self._call(self._poker.remove(self._room, self._secret, participant))

    async def toggle_lock(self) -> None:
        await self._call(self._poker.lock(self._room, self._secret, not (self._state or {}).get("locked")))

    async def open_tutorial(self) -> None:
        await self._tutorial.open(return_focus=self._ui["tutorial_open"])

    async def copy_bookmarklet(self) -> None:
        """the bookmark's address copied, for a browser that cannot drag it (pasted as a new bookmark's URL)"""
        copied = await self._dom.write_clipboard_text(self._bookmarklet())
        self._dom.set_text(self._ui["bookmarklet_copy"], self.t("poker.tutorial.copied" if copied else "poker.tutorial.copy_failed"))

    def _bookmarklet(self) -> str:
        return jira.bookmarklet(self._link(), {name: self.t(key) for name, key in BOOKMARKLET_TEXTS.items()})

    async def copy_link(self) -> None:
        copied = await self._dom.write_clipboard_text(self._link())
        self._dom.set_text(self._ui["copy"], self.t("poker.link_copied" if copied else "poker.copy_by_hand"))

    # ------------------------------------------------------------------ state

    async def _call(self, pending) -> Optional[dict]:
        """the server's answer applied, or None with its message shown"""
        try:
            answer = await pending
        except Exception as error:  # the server's refusal, said as it says it
            message = _message(error)
            if message == NOT_FOUND:
                await self._follow(None)
                self._room, self._state, self._me = None, None, None
                self._draw()
            self._error(message)
            return None
        self._error("")
        self._apply(answer, answer.get("me"))
        return answer

    def _apply(self, state: dict, me: Optional[str]) -> None:
        if self._state and state.get("room") == self._state.get("room") and \
                (state.get("stamp") or 0) < (self._state.get("stamp") or 0):
            return  # an older state arriving late
        was_joined = self._me is not None
        task = (state.get("task") or {}).get("id")
        if task != ((self._state or {}).get("task") or {}).get("id"):
            self._chosen = ""
        self._state, self._me = state, me
        if was_joined and me is not None and not any(person["id"] == me for person in state.get("participants") or []):
            self._me = None
            self._error("poker.removed")
        self._draw()

    async def _follow(self, room: Optional[str]) -> None:
        """the room's topic followed (None: none)"""
        topic = room_topic(room) if room else None
        if topic == self._topic:
            return
        if self._topic:
            await self._subscriptions.unsubscribe(self._topic)
        self._topic = topic
        if topic:
            await self._subscriptions.subscribe(topic)

    def _hash(self) -> str:
        return self._dom.location().partition("#")[2].strip()

    def _link(self) -> str:
        return browser.page_address(self._dom.location().partition("#")[0] + "#" + (self._room or ""))

    def _nickname(self) -> str:
        nickname = " ".join(self._dom.get_value(self._ui["nickname"]).split())
        self._dom.save_preference(NICKNAME_KEY, nickname)
        return nickname

    def _error(self, text: str) -> None:
        """text: a key, a coded message (the server's refusals) or a plain text, shown in the page's language"""
        self._error_text = text
        self._dom.set_text(self._ui["error"], self.t(text) if text else "")
        self._show(self._ui["error"], bool(text))

    # ------------------------------------------------------------------ drawing

    def _el(self, parent: Any, tag: str, cls: str = "", text: str = "", key: str = "", keys: Optional[dict] = None,
            **attributes: str) -> Any:
        """text: shown as written; key: a static text, keys: {attribute: key}, relabelled when the language changes"""
        element = self._dom.create_element(tag)
        if cls:
            self._dom.set_attribute(element, "class", cls)
        if text:
            self._dom.set_text(element, text)
        if key:
            self._b.text(element, key)
        for name, value in attributes.items():
            self._dom.set_attribute(element, name.rstrip("_").replace("_", "-"), value)
        for name, attribute_key in (keys or {}).items():
            self._b.text(element, attribute_key, name.rstrip("_").replace("_", "-"))
        if parent is not None:
            self._dom.append_child(parent, element)
        return element

    def _button(self, parent: Any, cls: str, text: str, action, **attributes: Any) -> Any:
        button = self._el(parent, "button", cls, text, type="button", **attributes)
        self._dom.on_click(button, action)
        return button

    def _show(self, element: Any, shown: bool) -> None:
        if shown:
            self._dom.remove_attribute(element, "hidden")
        else:
            self._dom.set_attribute(element, "hidden", "")

    def _build(self, mount: Any) -> None:
        ui = self._ui
        app = self._el(mount, "div", "pp-app")
        header = self._el(app, "header", "pp-header")
        self._el(header, "span", "pp-brand", key="poker.brand")
        end = self._el(header, "div", "pp-header-end")
        ui["tools"] = tools = self._el(end, "div", "pp-tools")
        ui["me"] = self._el(tools, "span", "pp-me")
        ui["edit"] = self._button(tools, "pp-button pp-ghost pp-edit", "", self.toggle_profile, key="poker.edit",
                                  keys={"title": "poker.edit.title"}, aria_expanded="false", aria_controls="pp-profile")
        ui["lock"] = self._button(tools, "pp-button pp-ghost", "", self.toggle_lock)
        ui["copy"] = self._button(tools, "pp-button pp-ghost", "", self.copy_link, key="poker.copy_link")
        ui["language"] = self._language.render(end)
        self._b.text(ui["language"], "poker.language", "aria-label")
        ui["error"] = self._el(app, "p", "pp-error", role="alert", hidden="")

        ui["welcome"] = welcome = self._el(app, "section", "pp-welcome")
        ui["welcome_title"] = self._el(welcome, "h1", "pp-title")
        ui["welcome_text"] = self._el(welcome, "p", "pp-lead")
        form = self._el(welcome, "form", "pp-form")
        self._el(form, "label", "pp-label", key="poker.nickname", for_="pp-nickname")
        ui["nickname"] = self._el(form, "input", "pp-input", id="pp-nickname", maxlength=str(NICKNAME_MAX),
                                  autocomplete="nickname", keys={"placeholder": "poker.nickname.example"})
        self._dom.set_value(ui["nickname"], self._dom.load_preference(NICKNAME_KEY) or "")
        self._el(form, "span", "pp-label", key="poker.avatar_optional", id="pp-avatar-label")
        ui["welcome_picker"] = self._el(form, "div", "pp-picker", role="group", aria_labelledby="pp-avatar-label")
        ui["enter"] = self._el(form, "button", "pp-button pp-primary", type="submit")
        self._dom.on_submit(form, ui["enter"], lambda: self.join() if self._room else self.create())

        ui["room"] = room = self._el(app, "section", "pp-room")
        ui["profile"] = profile = self._el(room, "form", "pp-profile", id="pp-profile", hidden="")
        self._el(profile, "label", "pp-label", key="poker.nickname", for_="pp-profile-name")
        ui["profile_name"] = self._el(profile, "input", "pp-input", id="pp-profile-name", maxlength=str(NICKNAME_MAX),
                                      autocomplete="nickname")
        self._el(profile, "span", "pp-label", key="poker.avatar", id="pp-profile-avatar")
        ui["picker"] = self._el(profile, "div", "pp-picker", role="group", aria_labelledby="pp-profile-avatar")
        actions = self._el(profile, "div", "pp-profile-actions")
        ui["save"] = self._el(actions, "button", "pp-button pp-primary", key="poker.save", type="submit")
        ui["cancel"] = self._button(actions, "pp-button pp-ghost", "", self.close_profile, key="poker.cancel")
        self._dom.on_submit(profile, ui["save"], self.save_profile)
        task = self._el(room, "div", "pp-task")
        ui["task_title"] = self._el(task, "h2", "pp-task-title")
        ui["task_form"] = task_form = self._el(task, "form", "pp-task-form")
        self._el(task_form, "label", "pp-label", key="poker.task_number", for_="pp-task-number")
        ui["task_input"] = self._el(task_form, "input", "pp-input pp-input-small", id="pp-task-number",
                                    maxlength="33", placeholder="KP-111", autocapitalize="characters")
        self._el(task_form, "label", "pp-label", key="poker.task_parent", for_="pp-task-parent")
        ui["parent_input"] = self._el(task_form, "input", "pp-input pp-input-small", id="pp-task-parent",
                                      maxlength="33", placeholder="KP-100", autocapitalize="characters")
        ui["task_button"] = self._el(task_form, "button", "pp-button pp-primary", type="submit")
        self._dom.on_submit(task_form, ui["task_button"], self.next_task)

        ui["import"] = box = self._el(room, "div", "pp-import")
        ui["import_confirm"] = confirm = self._el(box, "div", "pp-import-confirm", role="status", hidden="")
        ui["import_text"] = self._el(confirm, "p", "pp-import-text")
        self._button(confirm, "pp-button pp-primary", "", self.import_pending, key="poker.import")
        self._button(confirm, "pp-button pp-ghost", "", self.drop_pending, key="poker.import.drop")
        help_row = self._el(box, "div", "pp-import-help")
        ui["tutorial_open"] = self._button(help_row, "pp-button pp-ghost pp-tutorial-open", "", self.open_tutorial,
                                           key="poker.import.help", aria_haspopup="dialog")
        self._el(help_row, "span", "pp-import-hint", key="poker.import.hint")
        ui["queue"] = self._el(room, "div", "pp-queue", hidden="")

        board = self._el(room, "div", "pp-board")
        ui["top"] = self._el(board, "div", "pp-seats")
        table = self._el(board, "div", "pp-table")
        ui["fx"] = self._el(table, "div", "pp-fx", aria_hidden="true")
        ui["status"] = self._el(table, "p", "pp-status")
        ui["table_actions"] = self._el(table, "div", "pp-table-actions")
        ui["bottom"] = self._el(board, "div", "pp-seats")

        ui["deck"] = self._el(room, "div", "pp-deck", role="group", keys={"aria-label": "poker.cards"})
        ui["results"] = self._el(room, "div", "pp-results")
        ui["recap"] = self._el(room, "div", "pp-recap")
        self._tutorial = Drawer(self._dom, self.t("poker.tutorial.title"), close_label=self.t("poker.close"))
        self._tutorial.render(app)
        self._dom.set_attribute(self._tutorial.element, "class", "yc-drawer pp-tutorial")
        ui["bookmarklet"], ui["bookmarklet_copy"] = tutorial.render(self._b, self._tutorial.body, self.copy_bookmarklet)
        footer = self._el(app, "footer", "pp-footer")
        self._el(footer, "span", "", key="poker.powered_by")
        self._el(footer, "a", "", "iPOPO", href=IPOPO_URL, target="_blank", rel="noopener")
        self._el(footer, "span", "", key="poker.and")
        self._el(footer, "a", "", "YCappuccino", href=YCAPPUCCINO_URL, target="_blank", rel="noopener")
        self._draw()

    def _draw(self) -> None:
        ui, state, me = self._ui, self._state, self._me
        joined = state is not None and me is not None
        self._show(ui["welcome"], not joined)
        self._show(ui["room"], joined)
        self._show(ui["tools"], joined)
        if not joined:
            self._before = None
            self._draw_welcome()
            return
        moments, self._before = view.moments(self._before, state, me, view.my_card(state, me, self._chosen))
        drawn = {key: value for key, value in state.items() if key not in ("stamp", "me")}
        elapsed = time.monotonic() - self._since
        if drawn == self._drawn and elapsed < MOMENT_SECONDS:  # the same state again (an answer and its topic
            # message, a ping): the animations go on from where they are
            moments = {key: value | self._moments.get(key, value) for key, value in moments.items()}
        else:
            self._since, elapsed = time.monotonic(), 0.0
        self._moments, self._drawn = moments, drawn
        self._dom.set_attribute(ui["room"], "style", f"--pp-elapsed: {elapsed:.2f}s")
        consensus = bool((state.get("task") or {}).get("revealed") and (state.get("results") or {}).get("consensus"))
        if consensus:
            self._dom.set_attribute(ui["room"], "data-consensus", "")
        else:
            self._dom.remove_attribute(ui["room"], "data-consensus")
        host = view.is_host(state, me)
        mine = next((seat for seat in view.seats(state, me) if seat["me"]), None)
        me_text = f"{mine['avatar']} {mine['nickname']}" if mine else ""
        self._dom.set_text(ui["me"], self.t("poker.me_host", me=me_text) if mine and host else me_text)
        self._show(ui["lock"], host)
        self._dom.set_text(ui["lock"], self.t("poker.unlock" if state.get("locked") else "poker.lock"))
        self._dom.set_attribute(ui["lock"], "aria-pressed", "true" if state.get("locked") else "false")
        task = state.get("task")
        self._dom.set_text(ui["task_title"], (self.t("poker.task", number=task["number"]) + (f" · {task['title']}" if task.get("title") else ""))
                           if task else self.t("poker.no_task"))
        self._show(ui["task_form"], host and (not task or task.get("revealed")))
        self._show(ui["import"], host)
        self._draw_import(host)
        self._dom.set_text(ui["task_button"], self.t("poker.next_task" if task else "poker.start"))
        top, bottom = view.split(view.seats(state, me))
        self._draw_seats(ui["top"], top, host, 0)
        self._draw_seats(ui["bottom"], bottom, host, 1)
        self._draw_table(state, host)
        self._draw_results(state, host)
        self._draw_deck(state)
        self._draw_recap(state)

    def _draw_import(self, host: bool) -> None:
        """the import's confirmation (tickets received), the bookmarklet's link, the queue to pick the next ticket from"""
        ui, state = self._ui, self._state or {}
        self._dom.set_attribute(ui["bookmarklet"], "href", self._bookmarklet())
        self._show(ui["import_confirm"], host and self._pending is not None)
        if self._pending is not None:
            site, tickets = self._pending
            self._dom.set_text(ui["import_text"], self.t("poker.import.received_many" if len(tickets) > 1 else "poker.import.received_one",
                                                         count=len(tickets), site=site))
        task = state.get("task")
        box = ui["queue"]
        self._dom.clear(box)
        queue = state.get("queue") or []
        self._show(box, host and bool(queue))
        if not queue:
            return
        voting = bool(task) and not task.get("revealed")   # picking one now would drop the votes in progress
        self._el(box, "h3", "pp-recap-title", self.t("poker.queue"))
        if voting:
            self._el(box, "p", "pp-import-text", self.t("poker.queue.locked"))
        self._draw_queue(box, queue, voting)

    def _draw_queue(self, parent: Any, nodes: list, locked: bool) -> None:
        tree = self._el(parent, "ul", "pp-tree")
        for node in nodes:
            item = self._el(tree, "li", "")
            label = f"{node['number']} {node.get('title') or ''}".strip()
            button = self._button(item, "pp-queue-item", "", lambda number=node["number"]: self.play(number),
                                  aria_label=self.t("poker.queue.play", label=label), title=node.get("title") or node["number"])
            if locked:
                self._dom.set_attribute(button, "disabled", "")
            self._el(button, "span", "pp-kind is-" + (node.get("kind") or "task"), self.t(view.KIND_LABELS.get(node.get("kind"), "poker.kind.task")))
            self._el(button, "span", "pp-key", node["number"])
            self._el(button, "span", "pp-title-text", node.get("title") or "")
            if node.get("children"):
                self._draw_queue(item, node["children"], locked)

    def _draw_welcome(self) -> None:
        ui = self._ui
        self._draw_picker(ui["welcome_picker"], self._avatar, self.pick_avatar)
        count = len((self._state or {}).get("participants") or [])
        if self._room:
            self._dom.set_text(ui["welcome_title"], self.t("poker.join.title"))
            self._dom.set_text(ui["welcome_text"], self.t("poker.join.lead_many" if count > 1 else "poker.join.lead_one", count=count))
            self._dom.set_text(ui["enter"], self.t("poker.join"))
        else:
            self._dom.set_text(ui["welcome_title"], self.t("poker.brand"))
            self._dom.set_text(ui["welcome_text"], self.t("poker.welcome.lead"))
            self._dom.set_text(ui["enter"], self.t("poker.create"))

    def _draw_picker(self, box: Any, current: str, pick) -> None:
        """the avatars as toggle buttons, `current` pressed"""
        self._dom.clear(box)
        for avatar in AVATARS:
            self._button(box, "pp-avatar-choice" + (" is-selected" if avatar == current else ""), avatar,
                         lambda chosen=avatar: pick(chosen), aria_pressed="true" if avatar == current else "false",
                         aria_label=self.t("poker.avatar.one", avatar=avatar))

    def _draw_seats(self, row: Any, seats: list, host: bool, offset: int) -> None:
        self._dom.clear(row)
        moments = self._moments
        for index, seat in enumerate(seats):
            order = str(offset + 2 * index)  # around the table: top and bottom rows alternate
            classes = "pp-seat" + (" is-me" if seat["me"] else "") + (" is-new" if seat["id"] in moments.get("joined", ()) else "") \
                + (" is-fresh" if seat["id"] in moments.get("voted", ()) else "")
            element = self._el(row, "div", classes, data_participant=seat["id"], style=f"--i: {order}")
            card = self._el(element, "div", f"pp-card is-{seat['face']}" + (" is-flip" if moments.get("flip") else ""),
                            aria_label=self.t("poker.card." + seat["face"]) if seat["face"] in ("empty", "down") else seat["card"])
            if seat["face"] == "up":
                self._dom.set_text(card, seat["card"])
                self._dom.set_attribute(card, "data-card", seat["card"])
            if seat["me"]:
                self._button(element, "pp-avatar", seat["avatar"], self.toggle_profile, aria_label=self.t("poker.edit_profile"),
                             title=self.t("poker.edit_profile"))
            else:
                self._el(element, "span", "pp-avatar", seat["avatar"], aria_hidden="true")
            name = self._el(element, "div", "pp-name")
            self._el(name, "span", "", seat["nickname"])
            if seat["host"]:
                self._el(name, "span", "pp-badge", self.t("poker.host"))
            if host and not seat["me"]:
                self._button(element, "pp-remove", "×", lambda who=seat["id"]: self.remove(who),
                             aria_label=self.t("poker.remove", nickname=seat["nickname"]), title=self.t("poker.remove", nickname=seat["nickname"]))

    def _draw_table(self, state: dict, host: bool) -> None:
        ui = self._ui
        self._dom.set_text(ui["status"], view.status(state, self._me, self.t))
        self._dom.clear(ui["table_actions"])
        self._dom.clear(ui["fx"])
        if self._moments.get("flip"):  # 3, 2, 1, then the cards flip (CSS)
            countdown = self._el(ui["fx"], "div", "pp-countdown")
            for number in ("3", "2", "1"):
                self._el(countdown, "span", "", number)
        if self._moments.get("celebrate"):  # a consensus: confetti (CSS)
            confetti = self._el(ui["fx"], "div", "pp-confetti")
            for _ in range(18):
                self._el(confetti, "i")
        task = state.get("task")
        if not task or not host:
            return
        if task.get("revealed"):
            self._button(ui["table_actions"], "pp-button pp-ghost", self.t("poker.revote"), self.revote)
        else:
            self._button(ui["table_actions"], "pp-button pp-primary pp-reveal", self.t("poker.reveal"), self.reveal)

    def _draw_results(self, state: dict, host: bool) -> None:
        box = self._ui["results"]
        self._dom.clear(box)
        fresh = self._moments.get("flip")
        consensus = bool((state.get("results") or {}).get("consensus"))
        self._dom.set_attribute(box, "class", "pp-results" + (" is-consensus" if consensus else "") + (" is-fresh" if fresh else ""))
        lines = view.results(state, self._locale.language)
        self._show(box, bool(lines))
        if not lines:
            return
        if consensus:
            self._el(box, "p", "pp-consensus", self.t("poker.consensus"))
        stats = self._el(box, "dl", "pp-stats")
        for label, value in lines:
            item = self._el(stats, "div", "pp-stat")
            self._el(item, "dt", "", self.t(label))
            number = self._el(item, "dd", "", value)
            separator = "," if "," in value else "."
            whole, _, fraction = value.partition(separator)
            if fresh and label == view.AVERAGE and whole.isdigit():  # counts up from 0 (CSS, the text stays the value)
                self._dom.set_attribute(number, "class", "pp-count")
                self._dom.set_attribute(number, "style", f"--pp-n: {whole}")
                self._dom.set_attribute(number, "data-fraction", f"{separator}{fraction}" if fraction else "")
        bars = self._el(box, "div", "pp-distribution")
        for card, count in view.distribution(state):
            self._el(bars, "span", "pp-chip", f"{card} × {count}")
        final = (state.get("task") or {}).get("final") or ""
        choose = self._el(box, "div", "pp-final")
        self._el(choose, "span", "pp-label", self.t("poker.final"))
        if host:
            for card in DECK:
                if card in ("?", "☕"):
                    continue
                self._button(choose, "pp-chip pp-choice" + (" is-selected" if card == final else ""), card,
                             lambda chosen=card: self.set_final(chosen), aria_pressed="true" if card == final else "false")
        else:
            self._el(choose, "strong", "pp-final-value", final or "–")

    def _draw_deck(self, state: dict) -> None:
        deck = self._ui["deck"]
        self._dom.clear(deck)
        active = view.can_vote(state, self._me)
        mine = view.my_card(state, self._me, self._chosen)
        moments = self._moments
        self._show(deck, active)
        for index, card in enumerate(DECK):
            classes = "pp-deck-card" + (" is-selected" if card == mine else "") + (" is-dealt" if moments.get("deal") else "") \
                + (" is-picked" if card == mine and moments.get("picked") else "")
            button = self._button(deck, classes, card, lambda chosen=card: self.vote(chosen),
                                  aria_pressed="true" if card == mine else "false", data_card=card, style=f"--i: {index}")
            if not active:
                self._dom.set_attribute(button, "disabled", "")

    def _draw_recap(self, state: dict) -> None:
        box = self._ui["recap"]
        self._dom.clear(box)
        rows, total = view.recap(state, self._locale.language)
        self._show(box, bool(rows))
        if not rows:
            return
        self._el(box, "h3", "pp-recap-title", self.t("poker.recap"))
        table = self._el(box, "table", "pp-recap-table")
        head = self._el(self._el(table, "thead"), "tr")
        self._el(head, "th", "", self.t("poker.recap.task"))
        self._el(head, "th", "", self.t("poker.recap.estimate"))
        nested = any(row["sub"] for row in rows)
        if nested:
            self._el(head, "th", "", self.t("poker.recap.below"), title=self.t("poker.recap.below.title"))
        divided = any(row["divided"] for row in rows)
        if divided:
            self._el(head, "th", "pp-divided", f"÷ {view.STORY_DIVISOR}", aria_label=self.t("poker.recap.divided", n=view.STORY_DIVISOR),
                     title=self.t("poker.recap.divided.title", n=view.STORY_DIVISOR))
        body = self._el(table, "tbody")
        for row in rows:
            line = self._el(body, "tr", f"pp-depth-{min(row['depth'], 4)}" + (" is-parent" if row["sub"] else ""))
            cell = self._el(self._el(line, "td", "pp-recap-task"), "div", "pp-recap-line")
            if row["kind"]:
                self._el(cell, "span", "pp-kind is-" + row["kind"], self.t(view.KIND_LABELS[row["kind"]]) if row["kind"] in view.KIND_LABELS else "")
            self._el(cell, "span", "pp-key", row["number"])
            if row["title"]:
                self._el(cell, "span", "pp-title-text", row["title"])
            self._el(line, "td", "", row["final"])
            if nested:
                self._el(line, "td", "pp-sub", row["sub"])
            if divided:
                self._el(line, "td", "pp-divided", row["divided"])
        foot = self._el(self._el(table, "tfoot"), "tr")
        self._el(foot, "td", "", self.t("poker.recap.total"))
        self._el(foot, "td", "", total)
        if nested:
            self._el(foot, "td", "")
        if divided:
            self._el(foot, "td", "")


def _message(error: Exception) -> str:
    """the server's message, without the transport's prefix"""
    text = str(error.args[0]) if error.args else str(error)
    return text or "poker.error.no_answer"
