import unittest

from ycappuccino.planningpoker.deck import AVATARS, DECK, avatar, default_avatar, format_average, is_room_id, is_secret, nickname, results, task_number


class TestResults(unittest.TestCase):
    def test_average_nearest_min_max(self):
        summary = results(["3", "5", "8"])
        self.assertEqual((summary["average"], summary["nearest"], summary["min"], summary["max"]), (5.3, "5", "3", "8"))
        self.assertEqual(summary["counts"], {"3": 1, "5": 1, "8": 1})
        self.assertFalse(summary["consensus"])

    def test_a_tie_takes_the_higher_card_and_half_counts(self):
        self.assertEqual(results(["2", "3"])["nearest"], "3")  # 2.5: between 2 and 3
        self.assertEqual(results(["5", "5"])["average"], 5.0)
        self.assertTrue(results(["5", "5"])["consensus"])

    def test_question_and_coffee_are_not_numbers(self):
        summary = results(["?", "☕", "13"])
        self.assertEqual((summary["average"], summary["nearest"], summary["votes"]), (13.0, "13", 3))
        self.assertIsNone(results(["?", "☕"])["average"])
        self.assertIsNone(results([])["nearest"])

    def test_the_deck(self):
        self.assertEqual(DECK, ("0", "1", "2", "3", "5", "8", "13", "21", "34", "55", "89", "?", "☕"))
        self.assertNotIn("½", DECK)
        self.assertEqual(format_average(5.25), "5,2")
        self.assertEqual(format_average(8.0), "8")


class TestAvatars(unittest.TestCase):
    def test_only_the_list_is_valid(self):
        self.assertEqual(len(AVATARS), len(set(AVATARS)))
        self.assertTrue(16 <= len(AVATARS) <= 24)
        self.assertEqual(avatar(AVATARS[0]), AVATARS[0])
        for bad in ("", "x", "🇫🇷", "🦊🦊", None, 3):
            self.assertIsNone(avatar(bad))

    def test_the_default_is_stable_and_from_the_list(self):
        self.assertEqual(default_avatar("Alice"), default_avatar(" alice".strip().upper()))
        self.assertIn(default_avatar("Alice"), AVATARS)
        self.assertEqual(default_avatar("Alice"), default_avatar("Alice"))
        self.assertGreater(len({default_avatar(name) for name in ("Alice", "Bob", "Chloé", "Dan", "Eve", "Fay")}), 1)


class TestInputs(unittest.TestCase):
    def test_nicknames(self):
        self.assertEqual(nickname("  Chloé   Dupont "), "Chloé Dupont")
        self.assertEqual(nickname("o'neil-2"), "o'neil-2")
        for wrong in ("", "   ", "a" * 25, "<script>", "bob!", "-bob", "bob_", "a​b", None):
            self.assertIsNone(nickname(wrong), wrong)
        self.assertEqual(nickname("a" * 24), "a" * 24)

    def test_task_numbers(self):
        self.assertEqual(task_number(" #1234 "), "1234")
        for key in ("KP-111", "kp-111", "12a", "ABC_12.3"):
            self.assertEqual(task_number(key), key)
        for wrong in ("", "-1", "KP-", "1" * 33, "1 2", "KP–111", "<b>"):
            self.assertIsNone(task_number(wrong), wrong)

    def test_ids(self):
        self.assertTrue(is_secret("a" * 43))
        self.assertFalse(is_secret("short"))
        self.assertFalse(is_secret("a" * 42 + "/"))
        self.assertTrue(is_room_id("A" * 32))
        self.assertFalse(is_room_id("1"))
        self.assertFalse(is_room_id("../" + "a" * 30))
        self.assertFalse(is_room_id(None))
