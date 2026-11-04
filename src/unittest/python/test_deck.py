import unittest

from ycappuccino.planningpoker.deck import DECK, format_average, is_room_id, is_secret, nickname, results, task_number


class TestResults(unittest.TestCase):
    def test_average_nearest_min_max(self):
        summary = results(["3", "5", "8"])
        self.assertEqual((summary["average"], summary["nearest"], summary["min"], summary["max"]), (5.3, "5", "3", "8"))
        self.assertEqual(summary["counts"], {"3": 1, "5": 1, "8": 1})
        self.assertFalse(summary["consensus"])

    def test_a_tie_takes_the_higher_card_and_half_counts(self):
        self.assertEqual(results(["2", "3"])["nearest"], "3")  # 2.5: between 2 and 3
        self.assertEqual(results(["½", "½"])["average"], 0.5)
        self.assertTrue(results(["½", "½"])["consensus"])

    def test_question_and_coffee_are_not_numbers(self):
        summary = results(["?", "☕", "13"])
        self.assertEqual((summary["average"], summary["nearest"], summary["votes"]), (13.0, "13", 3))
        self.assertIsNone(results(["?", "☕"])["average"])
        self.assertIsNone(results([])["nearest"])

    def test_the_deck(self):
        self.assertEqual(DECK, ("0", "½", "1", "2", "3", "5", "8", "13", "21", "?", "☕"))
        self.assertEqual(format_average(5.25), "5,2")
        self.assertEqual(format_average(8.0), "8")


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
