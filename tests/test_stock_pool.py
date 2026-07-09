from datetime import datetime
from pathlib import Path

import pytest

import wealth_lab.stock_pool as stock_pool
from wealth_lab.models import Quote
from wealth_lab.stock_pool import (
    is_chinext_symbol,
    select_nested_random_a_share_pools,
    select_random_a_share_pool,
)


class FakeQuoteProvider:
    def fetch_spot_quotes(self, symbols: list[str] | None = None) -> list[Quote]:
        return [
            _quote("000001"),
            _quote("002031"),
            _quote("300001"),
            _quote("301001"),
            _quote("600000"),
            _quote("688001"),
            _quote("600001", price=25.0),
            _quote("000002", price=0.0),
        ]


class FailingQuoteProvider:
    def fetch_spot_quotes(self, symbols: list[str] | None = None) -> list[Quote]:
        raise RuntimeError("live quote source failed")


def test_select_random_a_share_pool_excludes_chinext_by_default() -> None:
    first = select_random_a_share_pool(
        count=3,
        seed=7,
        provider=FakeQuoteProvider(),
    )
    second = select_random_a_share_pool(
        count=3,
        seed=7,
        provider=FakeQuoteProvider(),
    )

    assert first.symbols == second.symbols
    assert first.exclude_chinext
    assert first.eligible_count == 5
    assert len(first.symbols) == 3
    assert not any(is_chinext_symbol(symbol) for symbol in first.symbols)
    assert "000002" not in first.symbols


def test_select_random_a_share_pool_can_include_chinext() -> None:
    selection = select_random_a_share_pool(
        count=6,
        seed=7,
        exclude_chinext=False,
        provider=FakeQuoteProvider(),
    )

    assert selection.eligible_count == 7
    assert any(is_chinext_symbol(symbol) for symbol in selection.symbols)


def test_select_random_a_share_pool_can_filter_by_max_price() -> None:
    selection = select_random_a_share_pool(
        count=4,
        seed=7,
        max_price=20.0,
        provider=FakeQuoteProvider(),
    )

    assert selection.max_price == 20.0
    assert selection.eligible_count == 4
    assert "600001" not in selection.symbols


def test_select_random_a_share_pool_rejects_oversized_request() -> None:
    with pytest.raises(ValueError, match="only 5 are eligible"):
        select_random_a_share_pool(
            count=6,
            seed=7,
            provider=FakeQuoteProvider(),
        )


def test_select_nested_random_a_share_pools_share_one_sample() -> None:
    selection = select_nested_random_a_share_pools(
        pool_sizes=[3, 1],
        seed=7,
        provider=FakeQuoteProvider(),
    )

    small, large = selection.pools

    assert selection.requested_sizes == (1, 3)
    assert small.symbols == large.symbols[:1]
    assert small.eligible_count == large.eligible_count == 5
    assert not any(is_chinext_symbol(symbol) for symbol in large.symbols)


def test_select_nested_random_a_share_pools_can_oversample_candidates() -> None:
    selection = select_nested_random_a_share_pools(
        pool_sizes=[3],
        seed=7,
        provider=FakeQuoteProvider(),
        candidate_count=10,
    )

    assert len(selection.pools[0].symbols) == 3
    assert len(selection.candidate_symbols) == 5
    assert selection.pools[0].symbols == selection.candidate_symbols[:3]


def test_select_nested_random_a_share_pools_uses_cached_universe_on_live_failure(
    tmp_path: Path,
) -> None:
    live_selection = select_nested_random_a_share_pools(
        pool_sizes=[3],
        seed=7,
        provider=FakeQuoteProvider(),
        cache_dir=tmp_path,
    )

    cached_selection = select_nested_random_a_share_pools(
        pool_sizes=[3],
        seed=7,
        provider=FailingQuoteProvider(),
        cache_dir=tmp_path,
    )

    assert live_selection.universe_source == "live"
    assert live_selection.universe_cache_path
    assert cached_selection.universe_source == "cache_after_live_failure"
    assert cached_selection.universe_cache_path
    assert cached_selection.pools[0].symbols == live_selection.pools[0].symbols
    assert not any(is_chinext_symbol(symbol) for symbol in cached_selection.pools[0].symbols)


def test_select_random_a_share_pool_can_prefer_cached_universe(
    tmp_path: Path,
) -> None:
    live_selection = select_random_a_share_pool(
        count=3,
        seed=7,
        provider=FakeQuoteProvider(),
        cache_dir=tmp_path,
    )

    cached_selection = select_random_a_share_pool(
        count=3,
        seed=7,
        provider=FailingQuoteProvider(),
        cache_dir=tmp_path,
        prefer_cache=True,
    )

    assert live_selection.universe_source == "live"
    assert cached_selection.universe_source == "cache"
    assert cached_selection.symbols == live_selection.symbols


def test_select_nested_random_a_share_pools_uses_tencent_fallback_without_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        stock_pool,
        "_fetch_tencent_quote_universe",
        lambda: (
            _quote("000001"),
            _quote("300001"),
            _quote("600000"),
        ),
    )

    selection = select_nested_random_a_share_pools(
        pool_sizes=[2],
        seed=7,
        provider=FailingQuoteProvider(),
        cache_dir=tmp_path,
    )

    assert selection.universe_source == "tencent_fallback"
    assert selection.universe_cache_path
    assert set(selection.pools[0].symbols) == {"000001", "600000"}


def _quote(symbol: str, price: float = 10.0) -> Quote:
    return Quote(
        symbol=symbol,
        name=symbol,
        price=price,
        change_pct=0.0,
        timestamp=datetime(2026, 7, 8, 10, 0),
        provider="fake",
    )
