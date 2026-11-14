import unittest

import ycappuccino.planningpoker.models.room  # noqa: F401
import ycappuccino.planningpoker.models.participant  # noqa: F401
import ycappuccino.planningpoker.models.vote  # noqa: F401
import ycappuccino.planningpoker.models.task  # noqa: F401

from ycappuccino.api.decorators import unbounded_items


class BoundedItemsTest(unittest.TestCase):
    def test_every_item_is_bounded(self):
        self.assertEqual(unbounded_items("ycappuccino.planningpoker"), [])


if __name__ == "__main__":
    unittest.main()
