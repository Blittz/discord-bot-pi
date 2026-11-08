import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.cogs.ark_players import ArkPlayers, safe_player_name


class ArkPlayerNotificationTests(unittest.IsolatedAsyncioTestCase):
    def make_cog(self, snapshot=None):
        cog = object.__new__(ArkPlayers)
        cog.snapshot = snapshot
        cog.queue = __import__("asyncio").Queue(maxsize=20)
        cog.service = SimpleNamespace(player_snapshot=AsyncMock())
        cog._enqueue = AsyncMock()
        return cog

    async def test_startup_baseline_does_not_announce(self):
        cog = self.make_cog()
        cog.service.player_snapshot.return_value = {"id:a": "Alice"}
        await cog._poll_once()
        cog._enqueue.assert_not_awaited()
        self.assertEqual(cog.snapshot, {"id:a": "Alice"})

    async def test_join_and_leave_announcements(self):
        cog = self.make_cog({"id:a": "Alice"})
        cog.service.player_snapshot.return_value = {"id:b": "Bob"}
        await cog._poll_once()
        calls = [call.args[0] for call in cog._enqueue.await_args_list]
        self.assertTrue(any("Bob joined ARK" in text for text in calls))
        self.assertTrue(any("Alice left ARK" in text for text in calls))

    async def test_empty_server_is_successful_and_announces_leaves(self):
        cog = self.make_cog({"id:a": "Alice", "id:b": "Bob"})
        cog.service.player_snapshot.return_value = {}
        await cog._poll_once()
        self.assertEqual(cog.snapshot, {})
        self.assertEqual(cog._enqueue.await_count, 2)

    async def test_failure_clears_baseline_without_false_leaves(self):
        cog = self.make_cog({"id:a": "Alice"})
        cog.service.player_snapshot.side_effect = ConnectionError()
        await cog._poll_once()
        self.assertIsNone(cog.snapshot)
        cog.service.player_snapshot.side_effect = None
        cog.service.player_snapshot.return_value = {"id:a": "Alice"}
        await cog._poll_once()
        cog._enqueue.assert_not_awaited()

    async def test_delivery_failure_does_not_crash_worker(self):
        cog = self.make_cog()
        channel = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("private")))
        cog._channel = AsyncMock(return_value=channel)
        worker = __import__("asyncio").create_task(cog._delivery_worker())
        cog.queue.put_nowait(SimpleNamespace(text="safe announcement"))
        await cog.queue.join()
        worker.cancel()
        self.assertTrue(channel.send.await_count == 1)

    def test_name_sanitization(self):
        value = safe_player_name("@everyone *Player* <@&123>")
        self.assertNotIn("@everyone", value)
        self.assertNotIn("<@&123>", value)
        self.assertNotIn("*", value)


if __name__ == "__main__":
    unittest.main()
