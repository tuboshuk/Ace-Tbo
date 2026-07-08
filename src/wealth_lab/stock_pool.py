"""Stock-pool selection helpers for replay training."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import random
from typing import Any, Iterable, Protocol

from wealth_lab.models import Quote
from wealth_lab.providers.efinance_provider import EfinanceProvider
from wealth_lab.rules import normalize_symbol


class QuoteUniverseProvider(Protocol):
    """Provider protocol for current A-share quote universes."""

    def fetch_spot_quotes(self, symbols: list[str] | None = None) -> list[Quote]:
        """Fetch spot quotes."""


@dataclass(frozen=True)
class StockPoolSelection:
    """A reproducible randomly selected training pool."""

    symbols: tuple[str, ...]
    seed: int
    requested_count: int
    eligible_count: int
    exclude_chinext: bool
    universe_source: str = "live"
    universe_cache_path: str | None = None


@dataclass(frozen=True)
class NestedStockPoolSelection:
    """Nested random pools drawn from one reproducible universe sample."""

    pools: tuple[StockPoolSelection, ...]
    seed: int
    requested_sizes: tuple[int, ...]
    eligible_count: int
    exclude_chinext: bool
    universe_source: str = "live"
    universe_cache_path: str | None = None


@dataclass(frozen=True)
class QuoteUniverse:
    """A full-market quote universe plus provenance."""

    quotes: tuple[Quote, ...]
    source: str
    cache_path: Path | None = None


def select_random_a_share_pool(
    *,
    count: int,
    seed: int,
    exclude_chinext: bool = True,
    provider: QuoteUniverseProvider | None = None,
    cache_dir: Path | None = None,
) -> StockPoolSelection:
    """Select a reproducible random A-share pool from current spot quotes."""

    if count <= 0:
        raise ValueError("count must be positive")
    quote_provider = provider or EfinanceProvider()
    universe = _load_quote_universe(quote_provider, cache_dir=cache_dir)
    eligible = _eligible_symbols_from_quotes(
        list(universe.quotes),
        exclude_chinext=exclude_chinext,
    )
    if count > len(eligible):
        raise ValueError(
            f"requested {count} symbols, but only {len(eligible)} are eligible"
        )
    rng = random.Random(seed)
    symbols = tuple(sorted(rng.sample(eligible, count)))
    return StockPoolSelection(
        symbols=symbols,
        seed=seed,
        requested_count=count,
        eligible_count=len(eligible),
        exclude_chinext=exclude_chinext,
        universe_source=universe.source,
        universe_cache_path=str(universe.cache_path) if universe.cache_path else None,
    )


def select_nested_random_a_share_pools(
    *,
    pool_sizes: Iterable[int],
    seed: int,
    exclude_chinext: bool = True,
    provider: QuoteUniverseProvider | None = None,
    cache_dir: Path | None = None,
) -> NestedStockPoolSelection:
    """Select nested reproducible A-share pools for expansion validation."""

    sizes = tuple(sorted(set(pool_sizes)))
    if not sizes:
        raise ValueError("pool_sizes must not be empty")
    if any(size <= 0 for size in sizes):
        raise ValueError("pool sizes must be positive")

    quote_provider = provider or EfinanceProvider()
    universe = _load_quote_universe(quote_provider, cache_dir=cache_dir)
    eligible = _eligible_symbols_from_quotes(
        list(universe.quotes),
        exclude_chinext=exclude_chinext,
    )
    max_size = sizes[-1]
    if max_size > len(eligible):
        raise ValueError(
            f"requested {max_size} symbols, but only {len(eligible)} are eligible"
        )

    rng = random.Random(seed)
    sampled = tuple(rng.sample(eligible, max_size))
    pools = tuple(
        StockPoolSelection(
            symbols=sampled[:size],
            seed=seed,
            requested_count=size,
            eligible_count=len(eligible),
            exclude_chinext=exclude_chinext,
            universe_source=universe.source,
            universe_cache_path=str(universe.cache_path) if universe.cache_path else None,
        )
        for size in sizes
    )
    return NestedStockPoolSelection(
        pools=pools,
        seed=seed,
        requested_sizes=sizes,
        eligible_count=len(eligible),
        exclude_chinext=exclude_chinext,
        universe_source=universe.source,
        universe_cache_path=str(universe.cache_path) if universe.cache_path else None,
    )


def is_chinext_symbol(symbol: str) -> bool:
    """Return whether a six-digit code belongs to ChiNext."""

    code = normalize_symbol(symbol)
    return code.startswith(("300", "301"))


def _eligible_symbols_from_quotes(
    quotes: list[Quote],
    *,
    exclude_chinext: bool,
) -> list[str]:
    return sorted(
        {
            normalize_symbol(quote.symbol)
            for quote in quotes
            if _is_eligible_a_share(quote, exclude_chinext=exclude_chinext)
        }
    )


def _is_eligible_a_share(quote: Quote, *, exclude_chinext: bool) -> bool:
    code = normalize_symbol(quote.symbol)
    if len(code) != 6:
        return False
    if exclude_chinext and is_chinext_symbol(code):
        return False
    if quote.price <= 0:
        return False
    return code.startswith(("0", "2", "3", "4", "6", "8"))


def _load_quote_universe(
    provider: QuoteUniverseProvider,
    *,
    cache_dir: Path | None,
) -> QuoteUniverse:
    try:
        quotes = tuple(provider.fetch_spot_quotes())
    except Exception as live_error:
        if cache_dir is None:
            quotes = _fetch_tencent_quote_universe()
            return QuoteUniverse(
                quotes=quotes,
                source="tencent_fallback",
                cache_path=None,
            )
        cached = _read_latest_quote_universe_cache(cache_dir)
        if cached is None:
            try:
                quotes = _fetch_tencent_quote_universe()
            except Exception:
                raise live_error
            cache_path = _write_quote_universe_cache(cache_dir, quotes)
            return QuoteUniverse(
                quotes=quotes,
                source="tencent_fallback",
                cache_path=cache_path,
            )
        return cached

    cache_path = _write_quote_universe_cache(cache_dir, quotes) if cache_dir else None
    return QuoteUniverse(
        quotes=quotes,
        source="live",
        cache_path=cache_path,
    )


def _fetch_tencent_quote_universe() -> tuple[Quote, ...]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("Install optional dependency: pip install requests") from exc

    url = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"
    page_size = 200
    offset = 0
    rows: list[dict[str, Any]] = []
    total: int | None = None
    while total is None or offset < total:
        response = requests.get(
            url,
            params={
                "_appver": "11.17.0",
                "board_code": "aStock",
                "sort_type": "price",
                "direct": "down",
                "offset": str(offset),
                "count": str(page_size),
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("tencent quote universe response missing data")
        page_rows = data.get("rank_list") or []
        if not isinstance(page_rows, list):
            raise RuntimeError("tencent quote universe response missing rank_list")
        rows.extend(page_rows)
        total = int(data.get("total") or len(rows))
        if not page_rows:
            break
        offset += len(page_rows)

    timestamp = datetime.now(timezone.utc)
    quotes = tuple(
        _quote_from_tencent_row(row, timestamp=timestamp)
        for row in rows
        if row.get("code")
    )
    if not quotes:
        raise RuntimeError("tencent quote universe returned no quotes")
    return quotes


def _quote_from_tencent_row(row: dict[str, Any], *, timestamp: datetime) -> Quote:
    raw_code = str(row.get("code", ""))
    symbol = raw_code[-6:].zfill(6)
    return Quote(
        symbol=symbol,
        name=str(row.get("name", "")),
        price=_float_or_zero(row.get("zxj")),
        change_pct=_optional_float(row.get("zdf")),
        timestamp=timestamp,
        provider="tencent-rank",
        amount=_optional_float(row.get("volume")),
        volume=_optional_int(row.get("turnover")),
        volume_ratio=_optional_float(row.get("lb")),
        turnover_rate=_optional_float(row.get("hsl")),
        high_20=None,
        low_20=None,
        sector=None,
    )


def _write_quote_universe_cache(
    cache_dir: Path | None,
    quotes: tuple[Quote, ...],
) -> Path | None:
    if cache_dir is None:
        return None
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema": "wealth_lab_quote_universe_v1",
            "created_at": created_at,
            "quote_count": len(quotes),
            "quotes": [_quote_to_cache_record(quote) for quote in quotes],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_path = cache_dir / f"{timestamp}-quote-universe.json"
        latest_path = cache_dir / "latest.json"
        snapshot_path.write_text(text, encoding="utf-8")
        latest_path.write_text(text, encoding="utf-8")
        return snapshot_path
    except OSError:
        return None


def _read_latest_quote_universe_cache(cache_dir: Path) -> QuoteUniverse | None:
    if not cache_dir.exists():
        return None
    paths = sorted(
        (path for path in cache_dir.glob("*.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload.get("quotes")
            if not isinstance(records, list):
                continue
            quotes = tuple(_quote_from_cache_record(record) for record in records)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if quotes:
            return QuoteUniverse(
                quotes=quotes,
                source="cache_after_live_failure",
                cache_path=path,
            )
    return None


def _quote_to_cache_record(quote: Quote) -> dict[str, Any]:
    return {
        "symbol": quote.symbol,
        "name": quote.name,
        "price": quote.price,
        "change_pct": quote.change_pct,
        "timestamp": quote.timestamp.isoformat(),
        "provider": quote.provider,
        "amount": quote.amount,
        "volume": quote.volume,
        "volume_ratio": quote.volume_ratio,
        "turnover_rate": quote.turnover_rate,
        "high_20": quote.high_20,
        "low_20": quote.low_20,
        "sector": quote.sector,
    }


def _quote_from_cache_record(record: dict[str, Any]) -> Quote:
    return Quote(
        symbol=str(record.get("symbol", "")).zfill(6),
        name=str(record.get("name", "")),
        price=_float_or_zero(record.get("price")),
        change_pct=_optional_float(record.get("change_pct")),
        timestamp=_parse_cache_timestamp(record.get("timestamp")),
        provider=str(record.get("provider", "quote-universe-cache")),
        amount=_optional_float(record.get("amount")),
        volume=_optional_int(record.get("volume")),
        volume_ratio=_optional_float(record.get("volume_ratio")),
        turnover_rate=_optional_float(record.get("turnover_rate")),
        high_20=_optional_float(record.get("high_20")),
        low_20=_optional_float(record.get("low_20")),
        sector=record.get("sector"),
    )


def _parse_cache_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(str(value))


def _float_or_zero(value: Any) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None else 0.0


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None
    return int(float(value))
