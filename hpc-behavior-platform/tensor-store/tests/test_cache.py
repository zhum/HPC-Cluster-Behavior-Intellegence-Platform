from __future__ import annotations

import numpy as np

from tensor_store.cache import DiskCache, make_key


def test_make_key_deterministic_and_order_independent():
    a = {"start": "2026-01-01", "end": "2026-01-02", "nodes": ["b", "a"]}
    b = {"nodes": ["b", "a"], "end": "2026-01-02", "start": "2026-01-01"}
    assert make_key(a) == make_key(b)


def test_make_key_differs_on_content():
    a = {"start": "2026-01-01"}
    b = {"start": "2026-01-02"}
    assert make_key(a) != make_key(b)


def test_put_get_round_trip(tmp_path):
    cache = DiskCache(tmp_path / "cache")
    key = make_key({"foo": "bar"})
    arrays = {"X": np.arange(6).reshape(2, 3).astype(np.float64)}
    meta = {"nodes": ["node-0", "node-1"], "count": 2}

    assert not cache.has(key)
    cache.put(key, arrays, meta)
    assert cache.has(key)

    got = cache.get(key)
    assert got is not None
    got_arrays, got_meta = got
    np.testing.assert_array_equal(got_arrays["X"], arrays["X"])
    assert got_meta == meta


def test_get_missing_returns_none(tmp_path):
    cache = DiskCache(tmp_path / "cache")
    assert cache.get("nonexistent") is None
