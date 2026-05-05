-- Backtest run history schema (WP-68)

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    strategy TEXT NOT NULL,
    instrument TEXT NOT NULL DEFAULT '',
    timeframe TEXT NOT NULL DEFAULT '',
    engine TEXT NOT NULL DEFAULT 'on_bar',
    period_start TEXT NOT NULL DEFAULT '',
    period_end TEXT NOT NULL DEFAULT '',
    param_variant TEXT NOT NULL DEFAULT '{}',      -- JSON
    matched_dates TEXT NOT NULL DEFAULT '[]',      -- JSON array of ISO dates
    net_pnl REAL NOT NULL DEFAULT 0.0,
    return_pct REAL NOT NULL DEFAULT 0.0,
    sharpe_ratio REAL NOT NULL DEFAULT 0.0,
    sortino_ratio REAL NOT NULL DEFAULT 0.0,
    max_drawdown REAL NOT NULL DEFAULT 0.0,
    win_rate REAL NOT NULL DEFAULT 0.0,
    profit_factor REAL NOT NULL DEFAULT 0.0,
    total_trades INTEGER NOT NULL DEFAULT 0,
    triggered_by TEXT NOT NULL DEFAULT '',         -- cli | engine | node | api
    status TEXT NOT NULL DEFAULT 'completed',      -- completed | failed | partial | queued
    artifact_path TEXT NOT NULL DEFAULT '',        -- optional JSON/parquet detail artifact
    notes TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_created ON backtest_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy ON backtest_runs(strategy);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_instrument ON backtest_runs(instrument);
