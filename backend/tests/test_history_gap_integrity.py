from datetime import datetime, timedelta, timezone

from app.services.cache import LruCache


def test_lru_remove_where_is_selective() -> None:
    cache = LruCache(default_ttl_seconds=60)
    cache.set(("tag", 20), "affected")
    cache.set(("tag", 23), "unrelated")
    assert cache.remove_where(lambda key: key[1] == 20) == 1
    assert cache.get(("tag", 20)) is None
    assert cache.get(("tag", 23)) == "unrelated"


def test_zero_is_not_a_gap_value() -> None:
    from app.schemas.pi import TimeSeriesPoint
    zero = TimeSeriesPoint(timestamp=datetime.now(timezone.utc), value=0.0)
    gap = TimeSeriesPoint(timestamp=datetime.now(timezone.utc) + timedelta(seconds=1), value=None)
    assert zero.value == 0.0
    assert gap.value is None
