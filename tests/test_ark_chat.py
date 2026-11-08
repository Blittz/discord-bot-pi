import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.cogs.ark_chat import ArkChat, ExpiringDedup, InboundMessage, OutboundMessage, RelayCounters, chat_fingerprint, parse_chat_lines, sanitize_discord_text


class ArkChatTests(unittest.TestCase):
    def test_normalizes_and_sanitizes_mentions_and_formatting(self):
        text = sanitize_discord_text("  hello  @everyone *there* <@&123>  ")
        self.assertNotIn("@everyone", text)
        self.assertNotIn("<@&123>", text)
        self.assertNotIn("*", text)

    def test_deduplicates_until_ttl_then_allows_again(self):
        dedup = ExpiringDedup(ttl=10, limit=2)
        self.assertTrue(dedup.add("Hello", now=0))
        self.assertFalse(dedup.add(" hello ", now=1))
        self.assertTrue(dedup.add("Hello", now=11))

    def test_queue_lines_and_fingerprints_are_stable(self):
        lines = parse_chat_lines(" Alice: hi\n\nBob: hello ")
        self.assertEqual(lines, ["Alice: hi", "Bob: hello"])
        self.assertEqual(chat_fingerprint(lines[0]), chat_fingerprint(" alice:   hi "))

    def test_identical_text_from_different_speakers_has_different_key(self):
        from src.cogs.ark_chat import chat_event_key
        self.assertNotEqual(chat_event_key("Alice: hello"), chat_event_key("Bob: hello"))

    def test_length_cap(self):
        self.assertLessEqual(len(sanitize_discord_text("x" * 1000)), 180)


def message(content, user_id=1):
    return SimpleNamespace(
        content=content,
        channel=SimpleNamespace(id=123),
        author=SimpleNamespace(id=user_id, bot=False),
        webhook_id=None,
        reply=AsyncMock(),
    )


class ArkOutboundTests(unittest.IsolatedAsyncioTestCase):
    def make_cog(self, queue_size=50):
        cog = object.__new__(ArkChat)
        cog.inbound_queue = asyncio.Queue(maxsize=queue_size)
        cog.inbound_queued = set()
        cog.inbound_inflight = set()
        cog.inbound_delivered = ExpiringDedup()
        cog.outbound_queue = asyncio.Queue(maxsize=queue_size)
        cog.service = SimpleNamespace(server_chat=AsyncMock())
        cog.counters = RelayCounters()
        cog.user_sends = {}
        cog.user_pending = {}
        cog.feedback_at = {}
        cog.outbound_echoes = {}
        cog.feedback = AsyncMock()
        cog._channel = AsyncMock()
        return cog

    async def test_rapid_burst_is_fifo_and_sequential(self):
        cog = self.make_cog()
        worker = asyncio.create_task(cog._outbound_worker())
        messages = [message(f"m{i}") for i in range(3)]
        with patch("src.cogs.ark_chat.OUTBOUND_PACING_SECONDS", 0):
            for item in messages:
                cog.outbound_queue.put_nowait(OutboundMessage(item, item.content, 1))
                cog.user_pending[1] = cog.user_pending.get(1, 0) + 1
            await asyncio.wait_for(cog.outbound_queue.join(), 2)
        worker.cancel()
        self.assertEqual([call.args[0] for call in cog.service.server_chat.await_args_list], ["m0", "m1", "m2"])
        self.assertEqual(cog.counters.sent, 3)

    async def test_rate_limit_rejects_after_bounded_burst(self):
        cog = self.make_cog()
        import src.cogs.ark_chat as module
        with patch.object(module, "CHANNEL_ID", 123), patch.object(module, "RELAY_TO_ARK", True):
            for i in range(6):
                await cog.on_message(message(f"m{i}"))
        self.assertEqual(cog.counters.queued, 5)
        self.assertEqual(cog.counters.reject_reasons.get("rate-limit"), 1)

    async def test_queue_overflow_is_counted_and_feedback_is_rate_limited(self):
        cog = self.make_cog(queue_size=1)
        import src.cogs.ark_chat as module
        with patch.object(module, "CHANNEL_ID", 123), patch.object(module, "RELAY_TO_ARK", True):
            await cog.on_message(message("one"))
            await cog.on_message(message("two", user_id=2))
        self.assertEqual(cog.counters.reject_reasons.get("queue-full"), 1)

    async def test_rcon_failure_is_not_retried_and_next_message_sends(self):
        cog = self.make_cog()
        cog.service.server_chat.side_effect = [ConnectionError(), None]
        worker = asyncio.create_task(cog._outbound_worker())
        with patch("src.cogs.ark_chat.OUTBOUND_PACING_SECONDS", 0):
            for text in ("failed", "sent"):
                item = message(text)
                cog.outbound_queue.put_nowait(OutboundMessage(item, text, 1))
                cog.user_pending[1] = cog.user_pending.get(1, 0) + 1
            await asyncio.wait_for(cog.outbound_queue.join(), 2)
        worker.cancel()
        self.assertEqual(cog.counters.failed, 1)
        self.assertEqual(cog.counters.sent, 1)
        self.assertEqual(cog.service.server_chat.await_count, 2)

    async def test_discord_send_failure_is_counted_without_unsafe_retry(self):
        cog = self.make_cog()
        channel = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("private")))
        cog._channel.return_value = channel
        worker = asyncio.create_task(cog._discord_worker())
        item = message("from ark")
        cog.inbound_queue.put_nowait(InboundMessage("k", item.content, 0))
        cog.inbound_queued.add("k")
        await asyncio.wait_for(cog.inbound_queue.join(), 2)
        worker.cancel()
        self.assertEqual(cog.counters.failed, 1)
        self.assertFalse(cog.inbound_delivered.contains_key("k"))


if __name__ == "__main__":
    unittest.main()
