"""Shared by the tests: an in-memory IManager (with the room trigger), a recording publisher, fake rate limits."""


class Model:
    def __init__(self, document: dict) -> None:
        self._document = document

    def get_storage_model(self) -> dict:
        return dict(self._document)


def _matches(record: dict, query: dict) -> bool:
    for key, wanted in query.items():
        value = record.get(key)
        if isinstance(wanted, dict) and "$lt" in wanted:
            if value is None or not value < wanted["$lt"]:
                return False
        elif value != wanted:
            return False
    return True


class MemoryManager:
    """the IManager calls the service makes; `triggers` run after each upsert, as storage's Manager runs them"""

    def __init__(self) -> None:
        self.items: dict = {}
        self.triggers: list = []

    async def up_sert(self, item: str, id: str, fields: dict, subject=None):
        record = self.items.setdefault(item, {}).setdefault(id, {"_id": id})
        record.update(fields)
        for trigger in self.triggers:
            if trigger.watches("upsert", item, True):
                await trigger.execute("upsert", item, Model(record))
        return Model(record)

    async def get_one(self, item: str, id: str, params=None, subject=None):
        record = self.items.get(item, {}).get(id)
        return Model(record) if record else None

    async def get_many(self, item: str, params=None, subject=None) -> list:
        query = (params or {}).get("filter") or {}
        found = [Model(r) for r in self.items.get(item, {}).values() if _matches(r, query)]
        return found[: (params or {}).get("limit") or None]

    async def delete(self, item: str, id: str, subject=None) -> None:
        self.items.get(item, {}).pop(id, None)

    async def delete_many(self, item: str, query: dict, subject=None) -> int:
        gone = [id for id, record in self.items.get(item, {}).items() if _matches(record, query)]
        for id in gone:
            del self.items[item][id]
        return len(gone)

    def of(self, item: str) -> list:
        return list(self.items.get(item, {}).values())


class Publisher:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, topic: str, message, subject=None) -> None:
        self.published.append((topic, message))


class NoLimits:
    def check(self, kind: str) -> None:
        pass

    def count(self, kind: str) -> None:
        pass
