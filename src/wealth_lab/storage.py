"""SQLite storage for cached bars, signals, and simulated fills."""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
from pathlib import Path
import json
from collections.abc import Iterator

from wealth_lab.models import (
    Bar,
    Fill,
    FundFlowSnapshot,
    Quote,
    SectorFundFlowSnapshot,
    StockSignal,
)


class SQLiteRepository:
    """Small SQLite repository used by local automation."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create tables if they do not exist."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS bars (
                    symbol TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    PRIMARY KEY (symbol, trade_date)
                );

                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    trade_date TEXT NOT NULL,
                    gross_amount REAL NOT NULL,
                    fees REAL NOT NULL,
                    reason TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS quotes (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price REAL NOT NULL,
                    change_pct REAL,
                    amount REAL,
                    volume INTEGER,
                    volume_ratio REAL,
                    turnover_rate REAL,
                    high_20 REAL,
                    low_20 REAL,
                    sector TEXT,
                    provider TEXT NOT NULL,
                    PRIMARY KEY (symbol, timestamp, provider)
                );

                CREATE TABLE IF NOT EXISTS fund_flows (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    period TEXT NOT NULL,
                    name TEXT NOT NULL,
                    main_net_inflow REAL NOT NULL,
                    main_net_inflow_pct REAL,
                    super_large_net_inflow REAL NOT NULL,
                    large_net_inflow REAL NOT NULL,
                    medium_net_inflow REAL NOT NULL,
                    small_net_inflow REAL NOT NULL,
                    change_pct REAL,
                    amount REAL,
                    turnover_rate REAL,
                    provider TEXT NOT NULL,
                    PRIMARY KEY (symbol, timestamp, period, provider)
                );

                CREATE TABLE IF NOT EXISTS sector_fund_flows (
                    name TEXT NOT NULL,
                    sector_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    period TEXT NOT NULL,
                    main_net_inflow REAL NOT NULL,
                    main_net_inflow_pct REAL,
                    super_large_net_inflow REAL NOT NULL,
                    large_net_inflow REAL NOT NULL,
                    medium_net_inflow REAL NOT NULL,
                    small_net_inflow REAL NOT NULL,
                    change_pct REAL,
                    leading_stock TEXT,
                    inflow_stock_count INTEGER,
                    provider TEXT NOT NULL,
                    PRIMARY KEY (name, sector_type, timestamp, period, provider)
                );

                CREATE TABLE IF NOT EXISTS stock_signals (
                    symbol TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    name TEXT NOT NULL,
                    fund_signal TEXT NOT NULL,
                    pattern_tags_json TEXT NOT NULL DEFAULT '[]',
                    anomalies_json TEXT NOT NULL,
                    score REAL NOT NULL,
                    reasons_json TEXT NOT NULL,
                    main_net_inflow REAL NOT NULL,
                    main_net_inflow_pct REAL,
                    super_large_net_inflow REAL NOT NULL,
                    large_net_inflow REAL NOT NULL,
                    change_pct REAL,
                    amount REAL,
                    turnover_rate REAL,
                    sector TEXT,
                    PRIMARY KEY (symbol, timestamp)
                );
                """
            )
            self._ensure_column(
                connection,
                "stock_signals",
                "pattern_tags_json",
                "TEXT NOT NULL DEFAULT '[]'",
            )

    def upsert_bars(self, bars: list[Bar]) -> None:
        """Insert or replace bars."""

        self.initialize()
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO bars (
                    symbol, trade_date, open, high, low, close, volume
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        bar.symbol,
                        bar.trade_date.isoformat(),
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                    )
                    for bar in bars
                ],
            )

    def insert_fills(self, fills: list[Fill]) -> None:
        """Persist simulated fills."""

        self.initialize()
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT INTO fills (
                    symbol, side, quantity, price, trade_date,
                    gross_amount, fees, reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        fill.symbol,
                        fill.side.value,
                        fill.quantity,
                        fill.price,
                        fill.trade_date.isoformat(),
                        fill.gross_amount,
                        fill.fees,
                        fill.reason,
                    )
                    for fill in fills
                ],
            )

    def upsert_quotes(self, quotes: list[Quote]) -> None:
        """Insert or replace quote snapshots."""

        self.initialize()
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO quotes (
                    symbol, timestamp, name, price, change_pct, amount, volume,
                    volume_ratio, turnover_rate, high_20, low_20, sector, provider
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        quote.symbol,
                        quote.timestamp.isoformat(),
                        quote.name,
                        quote.price,
                        quote.change_pct,
                        quote.amount,
                        quote.volume,
                        quote.volume_ratio,
                        quote.turnover_rate,
                        quote.high_20,
                        quote.low_20,
                        quote.sector,
                        quote.provider,
                    )
                    for quote in quotes
                ],
            )

    def upsert_fund_flows(self, snapshots: list[FundFlowSnapshot]) -> None:
        """Insert or replace stock fund-flow snapshots."""

        self.initialize()
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO fund_flows (
                    symbol, timestamp, period, name, main_net_inflow,
                    main_net_inflow_pct, super_large_net_inflow,
                    large_net_inflow, medium_net_inflow, small_net_inflow,
                    change_pct, amount, turnover_rate, provider
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot.symbol,
                        snapshot.timestamp.isoformat(),
                        snapshot.period,
                        snapshot.name,
                        snapshot.main_net_inflow,
                        snapshot.main_net_inflow_pct,
                        snapshot.super_large_net_inflow,
                        snapshot.large_net_inflow,
                        snapshot.medium_net_inflow,
                        snapshot.small_net_inflow,
                        snapshot.change_pct,
                        snapshot.amount,
                        snapshot.turnover_rate,
                        snapshot.provider,
                    )
                    for snapshot in snapshots
                ],
            )

    def upsert_sector_fund_flows(
        self,
        snapshots: list[SectorFundFlowSnapshot],
    ) -> None:
        """Insert or replace sector fund-flow snapshots."""

        self.initialize()
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO sector_fund_flows (
                    name, sector_type, timestamp, period, main_net_inflow,
                    main_net_inflow_pct, super_large_net_inflow,
                    large_net_inflow, medium_net_inflow, small_net_inflow,
                    change_pct, leading_stock, inflow_stock_count, provider
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot.name,
                        snapshot.sector_type,
                        snapshot.timestamp.isoformat(),
                        snapshot.period,
                        snapshot.main_net_inflow,
                        snapshot.main_net_inflow_pct,
                        snapshot.super_large_net_inflow,
                        snapshot.large_net_inflow,
                        snapshot.medium_net_inflow,
                        snapshot.small_net_inflow,
                        snapshot.change_pct,
                        snapshot.leading_stock,
                        snapshot.inflow_stock_count,
                        snapshot.provider,
                    )
                    for snapshot in snapshots
                ],
            )

    def upsert_stock_signals(self, signals: list[StockSignal]) -> None:
        """Insert or replace evaluated stock signals."""

        self.initialize()
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO stock_signals (
                    symbol, timestamp, name, fund_signal, pattern_tags_json,
                    anomalies_json, score, reasons_json, main_net_inflow,
                    main_net_inflow_pct, super_large_net_inflow, large_net_inflow,
                    change_pct, amount, turnover_rate, sector
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        signal.symbol,
                        signal.timestamp.isoformat(),
                        signal.name,
                        signal.fund_signal.value,
                        json.dumps(
                            [tag.value for tag in signal.pattern_tags],
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            [anomaly.value for anomaly in signal.anomalies],
                            ensure_ascii=False,
                        ),
                        signal.score,
                        json.dumps(list(signal.reasons), ensure_ascii=False),
                        signal.fund_flow.main_net_inflow,
                        signal.fund_flow.main_net_inflow_pct,
                        signal.fund_flow.super_large_net_inflow,
                        signal.fund_flow.large_net_inflow,
                        signal.fund_flow.change_pct,
                        signal.fund_flow.amount,
                        signal.fund_flow.turnover_rate,
                        signal.quote.sector if signal.quote else None,
                    )
                    for signal in signals
                ],
            )

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        cursor = connection.execute(f"PRAGMA table_info({table_name})")
        columns = {row[1] for row in cursor.fetchall()}
        if column_name not in columns:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
            )
