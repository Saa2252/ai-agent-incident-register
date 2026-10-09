"""Regression coverage for trigger parsing boundaries."""

import unittest

from rules.evaluate import ALWAYS, parse_trigger


class ParseTriggerTests(unittest.TestCase):
    def test_always_marker_has_no_question_or_required_answer(self) -> None:
        self.assertEqual(parse_trigger(ALWAYS), (None, None))

    def test_trigger_without_separator_has_an_empty_required_answer(self) -> None:
        self.assertEqual(parse_trigger("security_review"), ("security_review", ""))

    def test_only_the_first_separator_splits_question_from_answer(self) -> None:
        self.assertEqual(
            parse_trigger("security_review:approved:with-notes"),
            ("security_review", "approved:with-notes"),
        )

    def test_non_string_trigger_raises_attribute_error(self) -> None:
        with self.assertRaises(AttributeError):
            parse_trigger(object())


if __name__ == "__main__":
    unittest.main()
