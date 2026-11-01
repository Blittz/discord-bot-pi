import asyncio
from src.cogs.dadjoke import clean_joke, FALLBACK_JOKES, normalize_topic, THEMED_FALLBACKS

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
