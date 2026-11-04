"""PokerPage: the planning poker's page (French). Its room is the address's hash (`#<room id>`: never sent to the server
nor kept in its logs); its identity a secret this browser draws once and keeps (localStorage), bound by the server to the
nickname it joins with. It follows the room's topic (pubsub) and draws each state it receives; a (re)subscription asks
the state again, so nothing is missed across a reconnection. Draws through the page's DomBinding only."""

import asyncio
import logging
from typing import Any, Optional

from ycappuccino.api.pubsub import ISubscriber, ISubscriptionListener, ISubscriptions
from ycappuccino.ui_web.page import IWebPage

from ycappuccino.planningpoker.api import NOT_FOUND, IPlanningPoker, room_topic
from ycappuccino.planningpoker.deck import DECK, NICKNAME_MAX, is_room_id
from ycappuccino.planningpoker.page import browser, view

_logger = logging.getLogger(__name__)

SECRET_KEY = "planningpoker.secret"
NICKNAME_KEY = "planningpoker.nickname"
HEARTBEAT_SECONDS = 15  # well under the server's host_absent_seconds


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
        self._loading: Optional[asyncio.Future] = None
        self._topic: Optional[str] = None
        self._beating: Optional[asyncio.Future] = None

    async def start(self) -> None:
        self._dom = self._page.navigator().dom
        self._dom.set_document("Planning poker", "fr")
        self._secret = self._dom.load_preference(SECRET_KEY) or ""
        if len(self._secret) < 32:
            self._secret = browser.new_secret()
            self._dom.save_preference(SECRET_KEY, self._secret)
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
        self._state, self._me, self._chosen = None, None, ""
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
        answer = await self._call(self._poker.create_room(self._secret, nickname))
        if answer is None:
            return
        self._room = answer["room"]
        self._dom.replace_url(self._dom.location().partition("#")[0] + "#" + self._room)
        await self._follow(self._room)

    async def join(self) -> None:
        await self._call(self._poker.join(self._room, self._secret, self._nickname()))

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
        ui["enter"] = self._el(form, "button", "pp-button pp-primary", type="submit")
        self._dom.on_submit(form, ui["enter"], lambda: self.join() if self._room else self.create())

        ui["room"] = room = self._el(app, "section", "pp-room")
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
        ui["status"] = self._el(table, "p", "pp-status")
        ui["table_actions"] = self._el(table, "div", "pp-table-actions")
        ui["bottom"] = self._el(board, "div", "pp-seats")

        ui["deck"] = self._el(room, "div", "pp-deck", role="group", aria_label="Vos cartes")
        ui["results"] = self._el(room, "div", "pp-results")
        ui["recap"] = self._el(room, "div", "pp-recap")
        self._draw()

    def _draw(self) -> None:
        ui, state, me = self._ui, self._state, self._me
        joined = state is not None and me is not None
        self._show(ui["welcome"], not joined)
        self._show(ui["room"], joined)
        self._show(ui["tools"], joined)
        if not joined:
            self._draw_welcome()
            return
        host = view.is_host(state, me)
        mine = next((seat for seat in view.seats(state, me) if seat["me"]), None)
        self._dom.set_text(ui["me"], f"{mine['nickname']}{' · animateur' if host else ''}" if mine else "")
        self._show(ui["lock"], host)
        self._dom.set_text(ui["lock"], "Déverrouiller" if state.get("locked") else "Verrouiller")
        self._dom.set_attribute(ui["lock"], "aria-pressed", "true" if state.get("locked") else "false")
        task = state.get("task")
        self._dom.set_text(ui["task_title"], f"Tâche {task['number']}" if task else "Pas encore de tâche")
        self._show(ui["task_form"], host and (not task or task.get("revealed")))
        self._dom.set_text(ui["task_button"], "Tâche suivante" if task else "Commencer")
        top, bottom = view.split(view.seats(state, me))
        self._draw_seats(ui["top"], top, host)
        self._draw_seats(ui["bottom"], bottom, host)
        self._draw_table(state, host)
        self._draw_results(state, host)
        self._draw_deck(state)
        self._draw_recap(state)

    def _draw_welcome(self) -> None:
        ui = self._ui
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

    def _draw_seats(self, row: Any, seats: list, host: bool) -> None:
        self._dom.clear(row)
        for seat in seats:
            classes = "pp-seat" + (" is-me" if seat["me"] else "")
            element = self._el(row, "div", classes, data_participant=seat["id"])
            card = self._el(element, "div", f"pp-card is-{seat['face']}",
                            aria_label={"empty": "pas encore voté", "down": "a voté"}.get(seat["face"], seat["card"]))
            if seat["face"] == "up":
                self._dom.set_text(card, seat["card"])
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
        lines = view.results(state)
        self._show(box, bool(lines))
        if not lines:
            return
        stats = self._el(box, "dl", "pp-stats")
        for label, value in lines:
            item = self._el(stats, "div", "pp-stat")
            self._el(item, "dt", "", label)
            self._el(item, "dd", "", value)
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
        self._show(deck, active)
        for card in DECK:
            button = self._button(deck, "pp-deck-card" + (" is-selected" if card == mine else ""), card,
                                  lambda chosen=card: self.vote(chosen), aria_pressed="true" if card == mine else "false")
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
            self._el(row, "td", "", f"n° {number}")
            self._el(row, "td", "", final)
        foot = self._el(self._el(table, "tfoot"), "tr")
        self._el(foot, "td", "", "Total")
        self._el(foot, "td", "", total)


def _message(error: Exception) -> str:
    """the server's message, without the transport's prefix"""
    text = str(error.args[0]) if error.args else str(error)
    return text or "Le serveur ne répond pas, réessayez."
