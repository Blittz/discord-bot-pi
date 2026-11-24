import unittest

from src.bot import extensions_to_load


class ExtensionSelectionTest(unittest.TestCase):
    def test_ai_cog_is_off_by_default_switch(self):
        self.assertNotIn("cogs.chat", extensions_to_load(False))

    def test_ai_cog_loads_when_enabled(self):
        self.assertIn("cogs.chat", extensions_to_load(True))

    def test_only_the_ai_cog_differs(self):
        self.assertEqual(set(extensions_to_load(True)) - set(extensions_to_load(False)), {"cogs.chat"})

    def test_core_cogs_always_load(self):
        for ext in ("cogs.core", "cogs.admin", "cogs.audio", "cogs.photosaver", "cogs.ark"):
            self.assertIn(ext, extensions_to_load(False))


if __name__ == "__main__":
    unittest.main()
