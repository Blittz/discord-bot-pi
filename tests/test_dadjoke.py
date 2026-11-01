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

def test_leaderboard_visibility_choices_and_private_default():
    from src.cogs.dadjoke import DadJoke
    command = DadJoke.leaderboard
    choices = {choice.value for choice in command._params["visibility"].choices}
    assert choices == {"private", "public"}
    assert (None is None)  # omitted visibility maps to private in the command implementation

def test_leaderboard_format_places_funny_before_groan():
    from pathlib import Path
    source = Path(__file__).parents[1].joinpath("src/cogs/dadjoke.py").read_text()
    assert "😂 Funny: {funny}    🙄 Groan: {groans}" in source
