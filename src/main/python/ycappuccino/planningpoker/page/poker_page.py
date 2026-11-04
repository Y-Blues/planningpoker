"""PokerPage: the planning poker's page (French). Its room is the address's hash (`#<room id>`: never sent to the server
nor kept in its logs); its identity a secret this browser draws once and keeps (localStorage), bound by the server to the
nickname it joins with. It follows the room's topic (pubsub) and draws each state it receives; a (re)subscription asks
the state again, so nothing is missed across a reconnection. Draws through the page's DomBinding only."""

import asyncio
import logging
import time
from typing import Any, Optional

from ycappuccino.api.pubsub import ISubscriber, ISubscriptionListener, ISubscriptions
from ycappuccino.ui_web.page import IWebPage

from ycappuccino.planningpoker.api import NOT_FOUND, IPlanningPoker, room_topic
from ycappuccino.planningpoker.deck import AVATARS, DECK, NICKNAME_MAX, is_room_id
from ycappuccino.planningpoker.page import browser, view

_logger = logging.getLogger(__name__)

SECRET_KEY = "planningpoker.secret"
NICKNAME_KEY = "planningpoker.nickname"
AVATAR_KEY = "planningpoker.avatar"
IPOPO_URL = "https://github.com/tcalmant/ipopo"
YCAPPUCCINO_URL = "https://github.com/Y-Blues/core"
HEARTBEAT_SECONDS = 15  # well under the server's host_absent_seconds
MOMENT_SECONDS = 4  # the longest animation (the reveal's countdown, flips, confetti) is over by then


class PokerPage(ISubscriber, ISubscriptionListener):

    def __init__(self, page: IWebPage, poker: IPlanningPoker, subscriptions: ISubscriptions) -> None:
        self._page = page
        self._poker = poker
        self._subscriptions = subscriptions
        self._dom: Any = None
        self._ui: dict = {}
        self._room: Optional[str] = None
        self._state: Optional[dict] = None
        self._me: Optional[str] = None
        self._chosen = ""  # the card this page voted on the current task
        self._secret = ""
        self._picking = False  # the in-room picker is open
        self._avatar = ""  # the avatar picked on the join form ("": by nickname)
        self._loading: Optional[asyncio.Future] = None
        self._topic: Optional[str] = None
        self._beating: Optional[asyncio.Future] = None
        self._before: Optional[dict] = None  # the last drawing's snapshot (view.moments)
        self._moments: dict = {}  # what the current drawing animates
        self._drawn: Optional[dict] = None  # the state drawn last (its stamp aside)
        self._since = 0.0  # when the current moments started (a redraw resumes them where they are)

    async def start(self) -> None:
        self._dom = self._page.navigator().dom
        self._dom.set_document("Planning poker", "fr")
        self._secret = self._dom.load_preference(SECRET_KEY) or ""
        if len(self._secret) < 32:
            self._secret = browser.new_secret()
            self._dom.save_preference(SECRET_KEY, self._secret)
        saved = self._dom.load_preference(AVATAR_KEY) or ""
        self._avatar = saved if saved in AVATARS else ""
        self._build(self._page.navigator().mount)
        self._dom.on_navigate(lambda _url: self.open_room(self._hash()))
        self._loading = asyncio.ensure_future(self.open_room(self._hash()))
        self._beating = asyncio.ensure_future(self._heartbeat())

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
        await self._follow(self._room)

    async def join(self) -> None:
        await self._call(self._poker.join(self._room, self._secret, self._nickname(), self._avatar))

    async def pick_avatar(self, avatar: str) -> None:
        """the join form's choice (picking it again drops it), kept for next time"""
        self._avatar = "" if avatar == self._avatar else avatar
        self._dom.save_preference(AVATAR_KEY, self._avatar)
        self._draw_picker(self._ui["welcome_picker"], self._avatar, self.pick_avatar)

    async def set_avatar(self, avatar: str) -> None:
        self._picking = False
        self._show(self._ui["picker"], False)
        if await self._call(self._poker.set_avatar(self._room, self._secret, avatar)) is not None:
            self._avatar = avatar
            self._dom.save_preference(AVATAR_KEY, avatar)

    async def toggle_picker(self) -> None:
        self._picking = not self._picking
        self._show(self._ui["picker"], self._picking)

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
        if await self._call(self._poker.next_task(self._room, self._secret, number)) is not None:
            self._dom.set_value(self._ui["task_input"], "")

    async def remove(self, participant: str) -> None:
        await self._call(self._poker.remove(self._room, self._secret, participant))

    async def toggle_lock(self) -> None:
        await self._call(self._poker.lock(self._room, self._secret, not (self._state or {}).get("locked")))

    async def copy_link(self) -> None:
        copied = await self._dom.write_clipboard_text(self._link())
        self._dom.set_text(self._ui["copy"], "Lien copié ✓" if copied else "Copiez l'adresse de la page")

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
            self._error("Vous avez été retiré de la salle.")
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
        self._dom.set_text(self._ui["error"], text)
        self._show(self._ui["error"], bool(text))

    # ------------------------------------------------------------------ drawing

    def _el(self, parent: Any, tag: str, cls: str = "", text: str = "", **attributes: str) -> Any:
        element = self._dom.create_element(tag)
        if cls:
            self._dom.set_attribute(element, "class", cls)
        if text:
            self._dom.set_text(element, text)
        for name, value in attributes.items():
            self._dom.set_attribute(element, name.rstrip("_").replace("_", "-"), value)
        if parent is not None:
            self._dom.append_child(parent, element)
        return element

    def _button(self, parent: Any, cls: str, text: str, action, **attributes: str) -> Any:
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
        self._el(header, "span", "pp-brand", "Planning poker")
        ui["tools"] = tools = self._el(header, "div", "pp-tools")
        ui["me"] = self._el(tools, "span", "pp-me")
        ui["lock"] = self._button(tools, "pp-button pp-ghost", "Verrouiller", self.toggle_lock)
        ui["copy"] = self._button(tools, "pp-button pp-ghost", "Copier le lien", self.copy_link)
        ui["error"] = self._el(app, "p", "pp-error", role="alert", hidden="")

        ui["welcome"] = welcome = self._el(app, "section", "pp-welcome")
        ui["welcome_title"] = self._el(welcome, "h1", "pp-title")
        ui["welcome_text"] = self._el(welcome, "p", "pp-lead")
        form = self._el(welcome, "form", "pp-form")
        self._el(form, "label", "pp-label", "Votre pseudo", for_="pp-nickname")
        ui["nickname"] = self._el(form, "input", "pp-input", id="pp-nickname", maxlength=str(NICKNAME_MAX),
                                  autocomplete="nickname", placeholder="Ex. : Camille")
        self._dom.set_value(ui["nickname"], self._dom.load_preference(NICKNAME_KEY) or "")
        self._el(form, "span", "pp-label", "Votre avatar (facultatif)", id="pp-avatar-label")
        ui["welcome_picker"] = self._el(form, "div", "pp-picker", role="group", aria_labelledby="pp-avatar-label")
        ui["enter"] = self._el(form, "button", "pp-button pp-primary", type="submit")
        self._dom.on_submit(form, ui["enter"], lambda: self.join() if self._room else self.create())

        ui["room"] = room = self._el(app, "section", "pp-room")
        ui["picker"] = self._el(room, "div", "pp-picker pp-picker-room", role="group", aria_label="Choisir votre avatar",
                                hidden="")
        task = self._el(room, "div", "pp-task")
        ui["task_title"] = self._el(task, "h2", "pp-task-title")
        ui["task_form"] = task_form = self._el(task, "form", "pp-task-form")
        self._el(task_form, "label", "pp-label", "N° de tâche", for_="pp-task-number")
        ui["task_input"] = self._el(task_form, "input", "pp-input pp-input-small", id="pp-task-number",
                                    maxlength="33", placeholder="KP-111", autocapitalize="characters")
        ui["task_button"] = self._el(task_form, "button", "pp-button pp-primary", type="submit")
        self._dom.on_submit(task_form, ui["task_button"], self.next_task)

        board = self._el(room, "div", "pp-board")
        ui["top"] = self._el(board, "div", "pp-seats")
        table = self._el(board, "div", "pp-table")
        ui["fx"] = self._el(table, "div", "pp-fx", aria_hidden="true")
        ui["status"] = self._el(table, "p", "pp-status")
        ui["table_actions"] = self._el(table, "div", "pp-table-actions")
        ui["bottom"] = self._el(board, "div", "pp-seats")

        ui["deck"] = self._el(room, "div", "pp-deck", role="group", aria_label="Vos cartes")
        ui["results"] = self._el(room, "div", "pp-results")
        ui["recap"] = self._el(room, "div", "pp-recap")
        footer = self._el(app, "footer", "pp-footer", "Propulsé par ")
        self._el(footer, "a", "", "iPOPO", href=IPOPO_URL, target="_blank", rel="noopener")
        self._el(footer, "span", "", " et ")
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
        self._dom.set_text(ui["me"], f"{mine['avatar']} {mine['nickname']}{' · animateur' if host else ''}" if mine else "")
        self._draw_picker(ui["picker"], mine["avatar"] if mine else "", lambda chosen: self.set_avatar(chosen))
        self._show(ui["lock"], host)
        self._dom.set_text(ui["lock"], "Déverrouiller" if state.get("locked") else "Verrouiller")
        self._dom.set_attribute(ui["lock"], "aria-pressed", "true" if state.get("locked") else "false")
        task = state.get("task")
        self._dom.set_text(ui["task_title"], f"Tâche {task['number']}" if task else "Pas encore de tâche")
        self._show(ui["task_form"], host and (not task or task.get("revealed")))
        self._dom.set_text(ui["task_button"], "Tâche suivante" if task else "Commencer")
        top, bottom = view.split(view.seats(state, me))
        self._draw_seats(ui["top"], top, host, 0)
        self._draw_seats(ui["bottom"], bottom, host, 1)
        self._draw_table(state, host)
        self._draw_results(state, host)
        self._draw_deck(state)
        self._draw_recap(state)

    def _draw_welcome(self) -> None:
        ui = self._ui
        self._draw_picker(ui["welcome_picker"], self._avatar, self.pick_avatar)
        count = len((self._state or {}).get("participants") or [])
        if self._room:
            self._dom.set_text(ui["welcome_title"], "Rejoindre la salle")
            self._dom.set_text(ui["welcome_text"], f"{count} participant{'s' if count > 1 else ''} déjà présent"
                                                   f"{'s' if count > 1 else ''}. Choisissez un pseudo pour voter.")
            self._dom.set_text(ui["enter"], "Rejoindre")
        else:
            self._dom.set_text(ui["welcome_title"], "Planning poker")
            self._dom.set_text(ui["welcome_text"], "Estimez vos tâches en équipe : créez une salle, partagez son lien, "
                                                   "votez en même temps, révélez.")
            self._dom.set_text(ui["enter"], "Créer une salle")

    def _draw_picker(self, box: Any, current: str, pick) -> None:
        """the avatars as toggle buttons, `current` pressed"""
        self._dom.clear(box)
        for avatar in AVATARS:
            self._button(box, "pp-avatar-choice" + (" is-selected" if avatar == current else ""), avatar,
                         lambda chosen=avatar: pick(chosen), aria_pressed="true" if avatar == current else "false",
                         aria_label=f"Avatar {avatar}")

    def _draw_seats(self, row: Any, seats: list, host: bool, offset: int) -> None:
        self._dom.clear(row)
        moments = self._moments
        for index, seat in enumerate(seats):
            order = str(offset + 2 * index)  # around the table: top and bottom rows alternate
            classes = "pp-seat" + (" is-me" if seat["me"] else "") + (" is-new" if seat["id"] in moments.get("joined", ()) else "") \
                + (" is-fresh" if seat["id"] in moments.get("voted", ()) else "")
            element = self._el(row, "div", classes, data_participant=seat["id"], style=f"--i: {order}")
            card = self._el(element, "div", f"pp-card is-{seat['face']}" + (" is-flip" if moments.get("flip") else ""),
                            aria_label={"empty": "pas encore voté", "down": "a voté"}.get(seat["face"], seat["card"]))
            if seat["face"] == "up":
                self._dom.set_text(card, seat["card"])
                self._dom.set_attribute(card, "data-card", seat["card"])
            if seat["me"]:
                self._button(element, "pp-avatar", seat["avatar"], self.toggle_picker, aria_label="Changer d'avatar",
                             title="Changer d'avatar")
            else:
                self._el(element, "span", "pp-avatar", seat["avatar"], aria_hidden="true")
            name = self._el(element, "div", "pp-name")
            self._el(name, "span", "", seat["nickname"])
            if seat["host"]:
                self._el(name, "span", "pp-badge", "animateur")
            if host and not seat["me"]:
                self._button(element, "pp-remove", "×", lambda who=seat["id"]: self.remove(who),
                             aria_label=f"Retirer {seat['nickname']}", title=f"Retirer {seat['nickname']}")

    def _draw_table(self, state: dict, host: bool) -> None:
        ui = self._ui
        self._dom.set_text(ui["status"], view.status(state, self._me))
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
            self._button(ui["table_actions"], "pp-button pp-ghost", "Revoter", self.revote)
        else:
            self._button(ui["table_actions"], "pp-button pp-primary pp-reveal", "Révéler", self.reveal)

    def _draw_results(self, state: dict, host: bool) -> None:
        box = self._ui["results"]
        self._dom.clear(box)
        fresh = self._moments.get("flip")
        consensus = bool((state.get("results") or {}).get("consensus"))
        self._dom.set_attribute(box, "class", "pp-results" + (" is-consensus" if consensus else "") + (" is-fresh" if fresh else ""))
        lines = view.results(state)
        self._show(box, bool(lines))
        if not lines:
            return
        if consensus:
            self._el(box, "p", "pp-consensus", "Consensus !")
        stats = self._el(box, "dl", "pp-stats")
        for label, value in lines:
            item = self._el(stats, "div", "pp-stat")
            self._el(item, "dt", "", label)
            number = self._el(item, "dd", "", value)
            whole, _, fraction = value.partition(",")
            if fresh and label == "Moyenne" and whole.isdigit():  # counts up from 0 (CSS, the text stays the value)
                self._dom.set_attribute(number, "class", "pp-count")
                self._dom.set_attribute(number, "style", f"--pp-n: {whole}")
                self._dom.set_attribute(number, "data-fraction", f",{fraction}" if fraction else "")
        bars = self._el(box, "div", "pp-distribution")
        for card, count in view.distribution(state):
            self._el(bars, "span", "pp-chip", f"{card} × {count}")
        final = (state.get("task") or {}).get("final") or ""
        choose = self._el(box, "div", "pp-final")
        self._el(choose, "span", "pp-label", "Estimation retenue")
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
        rows, total = view.recap(state)
        self._show(box, bool(rows))
        if not rows:
            return
        self._el(box, "h3", "pp-recap-title", "Récapitulatif")
        table = self._el(box, "table", "pp-recap-table")
        head = self._el(self._el(table, "thead"), "tr")
        self._el(head, "th", "", "Tâche")
        self._el(head, "th", "", "Estimation")
        body = self._el(table, "tbody")
        for number, final in rows:
            row = self._el(body, "tr")
            self._el(row, "td", "", str(number))
            self._el(row, "td", "", final)
        foot = self._el(self._el(table, "tfoot"), "tr")
        self._el(foot, "td", "", "Total")
        self._el(foot, "td", "", total)


def _message(error: Exception) -> str:
    """the server's message, without the transport's prefix"""
    text = str(error.args[0]) if error.args else str(error)
    return text or "Le serveur ne répond pas, réessayez."
