-- Talim memory store schema

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    instrument TEXT NOT NULL,
    strategy TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    regime TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT 'pending',  -- pending, win, loss, scratch
    pnl REAL DEFAULT 0.0,
    approved INTEGER NOT NULL DEFAULT 1,      -- 1=approved, 0=rejected
    -- Architecture §5.1 spec columns (WP-21)
    signal_type TEXT NOT NULL DEFAULT 'entry', -- entry, exit, adjust
    atr_ratio REAL DEFAULT NULL,
    action TEXT NOT NULL DEFAULT '',           -- approve, reject, override
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_decisions_instrument ON decisions(instrument);
CREATE INDEX IF NOT EXISTS idx_decisions_strategy ON decisions(strategy);
CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON decisions(timestamp);

CREATE TABLE IF NOT EXISTS regime_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date TEXT NOT NULL UNIQUE,
    fingerprint BLOB NOT NULL,  -- 6 float64 values packed as bytes
    regime_label TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_regime_library_date ON regime_library(session_date);

CREATE TABLE IF NOT EXISTS strategy_activations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    strategy TEXT NOT NULL,
    action TEXT NOT NULL,        -- enable | disable
    actor TEXT NOT NULL DEFAULT 'operator',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_strategy_activations_strategy
    ON strategy_activations(strategy);
CREATE INDEX IF NOT EXISTS idx_strategy_activations_timestamp
    ON strategy_activations(timestamp);
