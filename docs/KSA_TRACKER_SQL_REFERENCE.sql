-- KSA Kitchen Tracker — SQL reference
-- Database: app/data/tracker.db (SQLite)
-- Tables are created in app/tracker_app.py; this file is for reference and Superset/BI.

-- ========== DDL (table definitions) ==========

CREATE TABLE IF NOT EXISTS ksa_kitchen_tracker (
    record_id TEXT NOT NULL,
    report_date TEXT NOT NULL,
    site_id TEXT NOT NULL,
    site_name TEXT,
    region TEXT NOT NULL DEFAULT 'KSA',
    metric_name TEXT NOT NULL,
    value REAL,
    status TEXT,
    notes TEXT,
    updated_at TEXT,
    PRIMARY KEY (record_id)
);

CREATE TABLE IF NOT EXISTS ksa_auto_refresh_execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    refresh_time TEXT NOT NULL,
    sheet TEXT NOT NULL,
    operation TEXT NOT NULL,
    status TEXT NOT NULL,
    user TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generic_tab_data (
    tab_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (tab_id, row_index)
);

-- ========== Useful queries ==========

-- Kitchen Tracker: all rows
SELECT * FROM ksa_kitchen_tracker ORDER BY report_date DESC, record_id;

-- Kitchen Tracker: by region
SELECT * FROM ksa_kitchen_tracker WHERE region = 'KSA' ORDER BY report_date DESC;

-- Execution log: latest first
SELECT id, refresh_time, sheet, operation, status, user
FROM ksa_auto_refresh_execution_log
ORDER BY refresh_time DESC;

-- Generic tab (e.g. SF Kitchen Data): data is JSON in data column
SELECT tab_id, row_index, data FROM generic_tab_data WHERE tab_id = 'SF Kitchen Data' ORDER BY row_index;
