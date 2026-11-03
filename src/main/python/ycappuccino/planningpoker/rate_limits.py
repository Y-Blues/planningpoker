"""RateLimits: per visitor address (the reverse proxy's X-Forwarded-For, api.http_server.VISITOR_ADDRESS) and kind of
call, permissions' Throttle: past `max` counted in `window` seconds, refused until the window slides. Configured:

    RateLimits:
      limits: {create: [10, 3600], join_failure: [30, 600], action: [300, 60]}

Counters live in this process only, like PasswordLogin's: a restart forgets them."""

from ycappuccino.api.endpoints_storage import InvalidRequest
from ycappuccino.api.http_server import VISITOR_ADDRESS
from ycappuccino.permissions.throttle import Throttle

from ycappuccino.planningpoker.api import IRateLimits

TOO_MANY = "Trop de tentatives, réessayez plus tard."
_DEFAULTS = {"create": [10, 3600], "join_failure": [30, 600], "action": [300, 60]}
_KEPT = 10000  # throttles beyond it: the idle ones dropped


class RateLimits(IRateLimits):

    def __init__(self, limits: dict = None) -> None:
        self._limits = {**_DEFAULTS, **(limits or {})}
        self._throttles: dict = {}

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def check(self, kind: str) -> None:
        try:
            self._throttle(kind).throttle()
        except InvalidRequest:
            raise InvalidRequest(TOO_MANY) from None

    def count(self, kind: str) -> None:
        self._throttle(kind).fail()

    def _throttle(self, kind: str) -> Throttle:
        key = (kind, VISITOR_ADDRESS.get() or "-")
        if key not in self._throttles and len(self._throttles) >= _KEPT:
            for idle in [other for other, throttle in self._throttles.items() if throttle.idle()]:
                del self._throttles[idle]
        maximum, window = self._limits[kind]
        return self._throttles.setdefault(key, Throttle(maximum, window))
