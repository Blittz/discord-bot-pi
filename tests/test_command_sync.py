import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


ROOT = Path(__file__).parents[1]


class CommandSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_sync_is_global_and_owner_only(self):
        from src.cogs.admin import Admin

        tree = SimpleNamespace(sync=AsyncMock(return_value=["one", "two"]))
        bot = SimpleNamespace(tree=tree)
        cog = Admin(bot)

        owner = SimpleNamespace(id=1)
        interaction = SimpleNamespace(
            user=owner,
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        with unittest.mock.patch("src.cogs.admin.OWNER_ID", 1):
            await cog.sync.callback(cog, interaction)

        tree.sync.assert_awaited_once_with()
        interaction.followup.send.assert_awaited_once_with("Synced 2 global commands.")

    async def test_non_owner_cannot_sync(self):
        from src.cogs.admin import Admin

        tree = SimpleNamespace(sync=AsyncMock())
        bot = SimpleNamespace(tree=tree)
        cog = Admin(bot)
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=2),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        with unittest.mock.patch("src.cogs.admin.OWNER_ID", 1):
            await cog.sync.callback(cog, interaction)

        tree.sync.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once_with("🔒 Owner only.", ephemeral=True)

    def test_startup_does_not_sync_and_no_guild_sync_remains(self):
        source = (ROOT / "src/bot.py").read_text()
        tree = ast.parse(source)
        setup = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "setup_hook")
        setup_source = ast.get_source_segment(source, setup)
        self.assertNotIn("tree.sync", setup_source)
        self.assertNotIn("copy_global_to", source)
        self.assertNotIn("sync(guild=", source)


if __name__ == "__main__":
    unittest.main()
