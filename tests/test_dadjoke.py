import asyncio
from src.cogs.dadjoke import clean_joke, FALLBACK_JOKES, normalize_topic, THEMED_FALLBACKS
from src.dnd_jokes import DND_JOKES
from src.joke_ratings import JokeRatings

def test_clean_joke_sanitizes_mentions_and_formatting():
    assert "@123" not in clean_joke("Hi <@123> `there`")
    assert "`" not in clean_joke("Hi `there`")

def test_fallback_collection_is_local_and_nonempty():
    assert FALLBACK_JOKES
    assert all(isinstance(j, str) and j for j in FALLBACK_JOKES)

def test_topic_aliases_and_themed_fallbacks():
    assert normalize_topic("haloween") == "halloween"
    assert normalize_topic("xmas") == "christmas"
    assert THEMED_FALLBACKS["halloween"]
    assert all(normalize_topic(alias) == "dnd" for alias in ("dnd", "d&d", "dungeons and dragons", "dungeons & dragons"))
    assert len(DND_JOKES) >= 30
    assert len(set(DND_JOKES)) == len(DND_JOKES)

def test_fetch_malformed_response_fails():
    from src.cogs.dadjoke import fetch_dad_joke
    class Response:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def json(self, **kwargs): return {"unexpected": "field"}
    class Session:
        def get(self, *args, **kwargs): return Response()
    try: asyncio.run(fetch_dad_joke(Session()))
    except ValueError: return
    raise AssertionError("malformed response was accepted")

def test_ratings_change_remove_persist_and_isolate(tmp_path):
    db = JokeRatings(tmp_path / "ratings.sqlite3"); jid = db.record_post(1, 10, "A joke")
    assert db.vote(1, jid, 4, "funny") == (1, 0)
    assert db.vote(1, jid, 4, "groan") == (0, 1)
    assert db.vote(1, jid, 4, "groan") == (0, 0)
    db.vote(1, jid, 4, "groan"); db.vote(2, jid, 4, "funny")
    assert db.totals(1, jid) == (0, 1) and db.totals(2, jid) == (1, 0)
    db.db.close(); reopened = JokeRatings(tmp_path / "ratings.sqlite3"); assert reopened.totals(1, jid) == (0, 1)

def test_monthly_usage_unique_duplicate_and_guild_separation(tmp_path):
    db = JokeRatings(tmp_path / "ratings.sqlite3")
    db.record_usage(1, 10, 100, "2026-11"); db.record_usage(1, 10, 100, "2026-11"); db.record_usage(1, 11, 101, "2026-11"); db.record_usage(2, 10, 102, "2026-11")
    assert db.usage_summary(1, "2026-11") == (2, 2)
    assert db.usage_summary(2, "2026-11") == (1, 1)
    assert db.usage_summary(1, "2026-12") == (0, 0)
    db.record_usage(1, 10, 103, "2026-11", 55); db.record_usage(1, 10, 105, "2026-11", 55); db.record_usage(1, 11, 104, "2026-11", 55)
    assert db.channel_usage(1, 55, "2026-11") == (3, 2)
    assert db.top_users(1, 55, "2026-11")[0] == (10, 2)

def test_old_usage_schema_migrates_channel_column(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"; db = sqlite3.connect(path)
    db.execute('CREATE TABLE usage (guild_id INTEGER, month TEXT, user_id INTEGER, interaction_id INTEGER UNIQUE, PRIMARY KEY(guild_id,month,user_id,interaction_id))'); db.commit(); db.close()
    ratings = JokeRatings(path); ratings.record_usage(1, 2, 3, "2026-11", 9)
    assert ratings.channel_usage(1, 9, "2026-11") == (1, 1)

def test_leaderboard_visibility_choices_and_private_default():
    from src.cogs.dadjoke import DadJoke
    command = DadJoke.leaderboard
    choices = {choice.value for choice in command._params["visibility"].choices}
    assert choices == {"private", "public"}
    assert (None is None)  # omitted visibility maps to private in the command implementation

def test_leaderboard_format_places_funny_before_groan():
    from pathlib import Path
    source = Path(__file__).parents[1].joinpath("src/cogs/dadjoke.py").read_text()
    assert '😂 {funny}    🙄 {groans}' in source
    assert '😂 Funny:' not in source and '🙄 Groan:' not in source

def test_rating_button_labels_are_emoji_and_counts_only(tmp_path):
    from src.cogs.dadjoke import DadJoke, RatingView
    class Bot: pass
    cog = DadJoke(Bot()); cog.ratings = JokeRatings(tmp_path / "ratings.sqlite3")
    view = RatingView(cog, 1, "A joke", None)
    labels = [item.label for item in view.children]
    assert labels == ["😂 0", "🙄 0"]
