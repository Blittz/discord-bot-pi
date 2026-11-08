import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.ark_stats import DeathEvent, RecordedDeath
from src.cogs.ark_players import ArkPlayers, safe_player_name


class ArkPlayerNotificationTests(unittest.IsolatedAsyncioTestCase):
    def make_cog(self, snapshot=None):
        cog = object.__new__(ArkPlayers)
        cog.snapshot = snapshot
        cog.queue = __import__("asyncio").Queue(maxsize=20)
        cog.service = SimpleNamespace(player_snapshot=AsyncMock())
        cog.stats = SimpleNamespace(
            server_outage=lambda: False,
            server_name=lambda: None,
            set_server_outage=lambda value: None,
            interrupt_snapshot=lambda: None,
            record_snapshot=lambda snapshot: None,
        )
        cog.latest_snapshot = {}
        cog._availability_initialized = False
        cog._rcon_failures = 0
        cog._outage_announced = False
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

    async def test_named_join_and_leave_announcements_use_cached_server_name(self):
        cog = self.make_cog({"id:a": "Alice"})
        cog.stats.server_name = lambda: "Vox Noctis"
        cog.service.player_snapshot.return_value = {"id:b": "Bob"}
        await cog._poll_once()
        calls = [call.args[0] for call in cog._enqueue.await_args_list]
        self.assertIn("🟢 Bob joined Vox Noctis! (1 player online)", calls)
        self.assertIn("🔴 Alice left Vox Noctis! (1 player online)", calls)

    async def test_join_leave_counts_are_singular_and_plural(self):
        cog = self.make_cog({})
        cog.stats.server_name = lambda: "Vox Noctis"
        cog.service.player_snapshot.return_value = {"id:a": "Alice", "id:b": "Bob"}
        await cog._poll_once()
        self.assertTrue(any("(2 players online)" in call.args[0] for call in cog._enqueue.await_args_list))
        cog._enqueue.reset_mock()
        cog.snapshot = {"id:a": "Alice", "id:b": "Bob"}
        cog.service.player_snapshot.return_value = {}
        await cog._poll_once()
        self.assertTrue(all("(0 players online)" in call.args[0] for call in cog._enqueue.await_args_list))

    async def test_named_announcements_sanitize_player_and_server_names(self):
        cog = self.make_cog({"id:a": "@everyone"})
        cog.stats.server_name = lambda: "<@&123> *Vox*"
        cog.service.player_snapshot.return_value = {"id:b": "<@123>"}
        await cog._poll_once()
        text = cog._enqueue.await_args_list[0].args[0]
        self.assertNotIn("@everyone", text)
        self.assertNotIn("<@&123>", text)
        self.assertNotIn("<@123>", text)
        self.assertNotIn("*", text)

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

    async def test_three_failures_emit_one_offline_and_recovery_emits_once(self):
        cog = self.make_cog({"id:a": "Alice"})
        cog._availability_initialized = True
        cog.service.player_snapshot.side_effect = ConnectionError()
        import src.cogs.ark_players as module
        with patch.object(module, "RELAY_TO_DISCORD", True):
            for _ in range(5):
                await cog._poll_once()
        messages = [call.args[0] for call in cog._enqueue.await_args_list]
        self.assertEqual(messages, ["🔴 **ARK server is offline.**"])
        cog.service.player_snapshot.side_effect = None
        cog.service.player_snapshot.return_value = {"id:a": "Alice"}
        with patch.object(module, "RELAY_TO_DISCORD", True):
            await cog._poll_once()
            await cog._poll_once()
        messages = [call.args[0] for call in cog._enqueue.await_args_list]
        self.assertEqual(messages.count("🟢 **ARK server is back online!**"), 1)

    async def test_initial_offline_period_does_not_announce(self):
        cog = self.make_cog()
        cog.service.player_snapshot.side_effect = ConnectionError()
        import src.cogs.ark_players as module
        with patch.object(module, "RELAY_TO_DISCORD", True):
            for _ in range(3):
                await cog._poll_once()
        cog._enqueue.assert_not_awaited()

    async def test_empty_success_after_outage_is_recovery_without_false_leave(self):
        cog = self.make_cog({"id:a": "Alice"})
        cog.snapshot = None
        cog._availability_initialized = True
        cog._outage_announced = True
        cog.service.player_snapshot.return_value = {}
        import src.cogs.ark_players as module
        with patch.object(module, "RELAY_TO_DISCORD", True):
            await cog._poll_once()
        messages = [call.args[0] for call in cog._enqueue.await_args_list]
        self.assertEqual(messages, ["🟢 **ARK server is back online!**"])

    async def test_death_announcement_formats_ordinary_and_total(self):
        cog = self.make_cog()
        await cog._enqueue_death(RecordedDeath(DeathEvent("a", "t", "Alice", 1, "Brontosaurus", 29, False), "id:a", 6))
        self.assertIn("💀 **Alice** was killed by a level 29 Brontosaurus (6 deaths total)", cog._enqueue.await_args.args[0])

    async def test_death_announcement_formats_zombified_and_unknown(self):
        cog = self.make_cog()
        await cog._enqueue_death(RecordedDeath(DeathEvent("a", "t", "Alice", 1, "Zombified Stegosaurus", 29, True), "id:a", 7))
        self.assertIn("🧟 **Alice** was killed by a level 29 Zombified Stegosaurus (7 deaths total)", cog._enqueue.await_args.args[0])
        cog._enqueue.reset_mock()
        await cog._enqueue_death(RecordedDeath(DeathEvent("b", "t", "Alice", 1, None, None, False), None, None))
        self.assertEqual(cog._enqueue.await_args.args[0], "💀 **Alice** died under mysterious circumstances")

    async def test_unassigned_death_omits_personal_total(self):
        cog = self.make_cog()
        await cog._enqueue_death(RecordedDeath(DeathEvent("a", "t", "@everyone", 1, "Rex", None, False), None, None))
        text = cog._enqueue.await_args.args[0]
        self.assertNotIn("deaths total", text)
        self.assertNotIn("@everyone", text)


if __name__ == "__main__":
    unittest.main()
