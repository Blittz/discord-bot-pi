import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from src.cogs import chat


def make_cog():
    cog = chat.Chat(SimpleNamespace(user=SimpleNamespace(id=1)))
    cog.enabled = True
    return cog


class ChatHelpersTest(unittest.TestCase):
    def test_channel_allowed_without_allow_list(self):
        with mock.patch.object(chat, "ALLOWED_CHANNELS", set()):
            self.assertTrue(chat.channel_allowed(123))

    def test_channel_allowed_with_allow_list(self):
        with mock.patch.object(chat, "ALLOWED_CHANNELS", {5}):
            self.assertTrue(chat.channel_allowed(5))
            self.assertFalse(chat.channel_allowed(6))

    def test_cooldown_blocks_repeat_requests_per_user(self):
        cog = make_cog()
        with mock.patch.object(chat, "AI_COOLDOWN_SECONDS", 10.0):
            self.assertEqual(cog._take_cooldown(1), 0.0)
            self.assertGreater(cog._take_cooldown(1), 0.0)
            self.assertEqual(cog._take_cooldown(2), 0.0)  # other users unaffected

    def test_cooldown_expires(self):
        cog = make_cog()
        with mock.patch.object(chat, "AI_COOLDOWN_SECONDS", 10.0):
            with mock.patch.object(chat.time, "monotonic", side_effect=[100.0, 111.0]):
                self.assertEqual(cog._take_cooldown(1), 0.0)
                self.assertEqual(cog._take_cooldown(1), 0.0)

    def test_cooldown_dict_stays_bounded(self):
        cog = make_cog()
        with mock.patch.object(chat, "AI_COOLDOWN_SECONDS", 10.0):
            with mock.patch.object(chat.time, "monotonic", return_value=1000.0):
                cog._last_request = {i: 0.0 for i in range(2000)}  # all expired
                cog._take_cooldown(99999)
        self.assertLessEqual(len(cog._last_request), 1)

    def test_error_details_are_not_leaked_to_users(self):
        cog = make_cog()
        with mock.patch.object(cog, "_complete", side_effect=RuntimeError("sk-secret-key-123")):
            with self.assertLogs(chat.log, level="ERROR"):
                result = asyncio.run(cog._answer("hi"))
        self.assertEqual(result, chat.GENERIC_ERROR)
        self.assertNotIn("sk-secret", result)

    def test_answer_is_truncated_and_never_empty(self):
        cog = make_cog()
        with mock.patch.object(cog, "_complete", return_value="x" * 5000):
            self.assertEqual(len(asyncio.run(cog._answer("hi"))), chat.MAX_REPLY_CHARS)
        with mock.patch.object(cog, "_complete", return_value=""):
            self.assertEqual(asyncio.run(cog._answer("hi")), "…")

    def test_replies_suppress_all_mentions(self):
        self.assertFalse(chat.NO_MENTIONS.everyone)
        self.assertFalse(chat.NO_MENTIONS.roles)
        self.assertFalse(chat.NO_MENTIONS.users)


if __name__ == "__main__":
    unittest.main()
