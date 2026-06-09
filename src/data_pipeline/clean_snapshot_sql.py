from __future__ import annotations

import time
from typing import Any, Iterable

import pandas as pd

from src.config import settings
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.tushare_client import SOURCE_PRIORITY_PRIMARY
from src.utils.dates import normalize_yyyymmdd


STAGING_TABLES = (
    "clean_snapshot_daily_raw_stage",
    "clean_snapshot_adj_factor_stage",
    "clean_snapshot_daily_basic_stage",
    "clean_snapshot_reference_factor_stage",
    "clean_snapshot_selected_stock_stage",
)


def _date_obj(value: object) -> object:
    return pd.to_datetime(value, errors="coerce").date()


def _stock_code_from_ts_code(value: object) -> str:
    return str(value or "").split(".", 1)[0].zfill(6)


def _ts_code_from_stock_code(stock_code: object) -> str:
    code = str(stock_code).zfill(6)
    if code.startswith(("4", "8", "920")):
        return f"{code}.BJ"
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 3)


def _normalize_code_list(stock_codes: Iterable[object]) -> list[str]:
    return sorted({str(code).strip().zfill(6) for code in stock_codes if str(code).strip()})


def _table_row_count(storage: DuckDBStorage, table: str, where_sql: str = "", params: list[object] | None = None) -> int:
    params = params or []
    sql = f"SELECT count(*) AS n FROM {table}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    df = storage.read_df(sql, params)
    return int(df.loc[0, "n"]) if not df.empty else 0


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="Float64")


def _text_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return frame[column].astype(str)
    return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="object")


def ensure_clean_snapshot_staging_tables(storage: DuckDBStorage) -> None:
    with storage.connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS clean_snapshot_daily_raw_stage (
              snapshot_build_id TEXT,
              ts_code TEXT,
              stock_code TEXT,
              trade_date DATE,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE,
              volume DOUBLE,
              amount DOUBLE,
              pct_chg DOUBLE
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS clean_snapshot_adj_factor_stage (
              snapshot_build_id TEXT,
              ts_code TEXT,
              stock_code TEXT,
              trade_date DATE,
              adj_factor DOUBLE
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS clean_snapshot_daily_basic_stage (
              snapshot_build_id TEXT,
              ts_code TEXT,
              stock_code TEXT,
              trade_date DATE,
              turnover DOUBLE,
              volume_ratio DOUBLE,
              total_mv DOUBLE,
              circ_mv DOUBLE
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS clean_snapshot_reference_factor_stage (
              snapshot_build_id TEXT,
              stock_code TEXT,
              reference_adj_factor DOUBLE,
              reference_trade_date DATE,
              PRIMARY KEY (snapshot_build_id, stock_code)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS clean_snapshot_selected_stock_stage (
              snapshot_build_id TEXT,
              stock_code TEXT,
              PRIMARY KEY (snapshot_build_id, stock_code)
            )
            """
        )


def clear_clean_snapshot_staging(storage: DuckDBStorage, snapshot_build_id: str) -> None:
    ensure_clean_snapshot_staging_tables(storage)
    with storage.connect() as con:
        for table in STAGING_TABLES:
            con.execute(f"DELETE FROM {table} WHERE snapshot_build_id = ?", [snapshot_build_id])


def cleanup_clean_snapshot_staging(storage: DuckDBStorage, snapshot_build_id: str) -> dict[str, object]:
    ensure_clean_snapshot_staging_tables(storage)
    started = time.monotonic()
    rows = 0
    with storage.connect() as con:
        for table in STAGING_TABLES:
            rows += int(
                con.execute(
                    f"SELECT count(*) AS n FROM {table} WHERE snapshot_build_id = ?",
                    [snapshot_build_id],
                ).fetchone()[0]
                or 0
            )
        for table in STAGING_TABLES:
            con.execute(f"DELETE FROM {table} WHERE snapshot_build_id = ?", [snapshot_build_id])
    return {"rows": int(rows), "duration_seconds": _elapsed(started)}


def stage_selected_stock_codes(storage: DuckDBStorage, snapshot_build_id: str, stock_codes: list[str]) -> int:
    codes = _normalize_code_list(stock_codes)
    if not codes:
        raise ValueError("selected_stock_codes is empty")
    frame = pd.DataFrame({"snapshot_build_id": snapshot_build_id, "stock_code": codes})
    storage.upsert_df("clean_snapshot_selected_stock_stage", frame, ["snapshot_build_id", "stock_code"])
    return len(frame)


def normalize_daily_raw_stage_frame(snapshot_build_id: str, df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "snapshot_build_id",
                "ts_code",
                "stock_code",
                "trade_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "pct_chg",
            ]
        )
    out = pd.DataFrame(index=df.index)
    out["snapshot_build_id"] = snapshot_build_id
    out["ts_code"] = _text_column(df, "ts_code")
    if "stock_code" in df.columns:
        out["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(df["stock_code"].astype(str)).str.zfill(6)
    else:
        out["stock_code"] = out["ts_code"].map(_stock_code_from_ts_code)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date if "trade_date" in df.columns else pd.NaT
    out["open"] = _numeric_column(df, "open")
    out["high"] = _numeric_column(df, "high")
    out["low"] = _numeric_column(df, "low")
    out["close"] = _numeric_column(df, "close")
    out["volume"] = _numeric_column(df, "volume") if "volume" in df.columns else _numeric_column(df, "vol")
    out["amount"] = _numeric_column(df, "amount")
    out["pct_chg"] = _numeric_column(df, "pct_chg")
    return out.dropna(subset=["stock_code", "trade_date"]).drop_duplicates(["snapshot_build_id", "stock_code", "trade_date"], keep="last")


def normalize_adj_factor_stage_frame(snapshot_build_id: str, df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["snapshot_build_id", "ts_code", "stock_code", "trade_date", "adj_factor"])
    out = pd.DataFrame(index=df.index)
    out["snapshot_build_id"] = snapshot_build_id
    out["ts_code"] = _text_column(df, "ts_code")
    if "stock_code" in df.columns:
        out["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(df["stock_code"].astype(str)).str.zfill(6)
    else:
        out["stock_code"] = out["ts_code"].map(_stock_code_from_ts_code)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date if "trade_date" in df.columns else pd.NaT
    out["adj_factor"] = _numeric_column(df, "adj_factor")
    out = out.dropna(subset=["stock_code", "trade_date", "adj_factor"])
    out = out[out["adj_factor"] > 0].copy()
    return out.drop_duplicates(["snapshot_build_id", "stock_code", "trade_date"], keep="last")


def normalize_daily_basic_stage_frame(snapshot_build_id: str, df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "snapshot_build_id",
                "ts_code",
                "stock_code",
                "trade_date",
                "turnover",
                "volume_ratio",
                "total_mv",
                "circ_mv",
            ]
        )
    out = pd.DataFrame(index=df.index)
    out["snapshot_build_id"] = snapshot_build_id
    out["ts_code"] = _text_column(df, "ts_code")
    if "stock_code" in df.columns:
        out["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(df["stock_code"].astype(str)).str.zfill(6)
    else:
        out["stock_code"] = out["ts_code"].map(_stock_code_from_ts_code)
    out["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce").dt.date if "trade_date" in df.columns else pd.NaT
    out["turnover"] = _numeric_column(df, "turnover") if "turnover" in df.columns else _numeric_column(df, "turnover_rate")
    out["volume_ratio"] = _numeric_column(df, "volume_ratio")
    out["total_mv"] = _numeric_column(df, "total_mv")
    out["circ_mv"] = _numeric_column(df, "circ_mv")
    return out.dropna(subset=["stock_code", "trade_date"]).drop_duplicates(["snapshot_build_id", "stock_code", "trade_date"], keep="last")


def append_clean_snapshot_stage_batch(
    storage: DuckDBStorage,
    snapshot_build_id: str,
    *,
    daily_frames: list[pd.DataFrame] | None = None,
    adj_frames: list[pd.DataFrame] | None = None,
    basic_frames: list[pd.DataFrame] | None = None,
    selected_stock_codes: list[str] | None = None,
) -> dict[str, object]:
    started = time.monotonic()
    code_set = set(_normalize_code_list(selected_stock_codes or []))
    counts = {"daily_raw_rows": 0, "adj_factor_rows": 0, "daily_basic_rows": 0}
    if daily_frames:
        daily = pd.concat(daily_frames, ignore_index=True)
        daily = normalize_daily_raw_stage_frame(snapshot_build_id, daily)
        if code_set:
            daily = daily[daily["stock_code"].isin(code_set)].copy()
        if not daily.empty:
            storage.insert_df("clean_snapshot_daily_raw_stage", daily)
            counts["daily_raw_rows"] = int(len(daily))
    if adj_frames:
        adj = pd.concat(adj_frames, ignore_index=True)
        adj = normalize_adj_factor_stage_frame(snapshot_build_id, adj)
        if code_set:
            adj = adj[adj["stock_code"].isin(code_set)].copy()
        if not adj.empty:
            storage.insert_df("clean_snapshot_adj_factor_stage", adj)
            counts["adj_factor_rows"] = int(len(adj))
    if basic_frames:
        basic = pd.concat(basic_frames, ignore_index=True)
        basic = normalize_daily_basic_stage_frame(snapshot_build_id, basic)
        if code_set:
            basic = basic[basic["stock_code"].isin(code_set)].copy()
        if not basic.empty:
            storage.insert_df("clean_snapshot_daily_basic_stage", basic)
            counts["daily_basic_rows"] = int(len(basic))
    counts["duration_seconds"] = _elapsed(started)
    return counts


def build_reference_factor_table(
    storage: DuckDBStorage,
    snapshot_build_id: str,
    end_date: str,
    selected_stock_codes: list[str] | None = None,
) -> dict[str, object]:
    ensure_clean_snapshot_staging_tables(storage)
    if selected_stock_codes is not None:
        stage_selected_stock_codes(storage, snapshot_build_id, selected_stock_codes)
    started = time.monotonic()
    end = _date_obj(normalize_yyyymmdd(end_date))
    with storage.connect() as con:
        con.execute("DELETE FROM clean_snapshot_reference_factor_stage WHERE snapshot_build_id = ?", [snapshot_build_id])
        con.execute(
            """
            INSERT INTO clean_snapshot_reference_factor_stage (
              snapshot_build_id, stock_code, reference_adj_factor, reference_trade_date
            )
            WITH eligible AS (
              SELECT
                a.stock_code,
                a.trade_date,
                a.adj_factor,
                row_number() OVER (PARTITION BY a.stock_code ORDER BY a.trade_date DESC) AS rn
              FROM clean_snapshot_adj_factor_stage a
              JOIN clean_snapshot_selected_stock_stage s
                ON s.snapshot_build_id = a.snapshot_build_id
               AND s.stock_code = a.stock_code
              WHERE a.snapshot_build_id = ?
                AND a.trade_date <= ?
                AND a.adj_factor IS NOT NULL
                AND a.adj_factor > 0
            )
            SELECT ?, stock_code, adj_factor, trade_date
            FROM eligible
            WHERE rn = 1
            """,
            [snapshot_build_id, end, snapshot_build_id],
        )
        missing = con.execute(
            """
            SELECT s.stock_code
            FROM clean_snapshot_selected_stock_stage s
            LEFT JOIN clean_snapshot_reference_factor_stage r
              ON r.snapshot_build_id = s.snapshot_build_id
             AND r.stock_code = s.stock_code
            WHERE s.snapshot_build_id = ?
              AND r.stock_code IS NULL
            ORDER BY s.stock_code
            LIMIT 20
            """,
            [snapshot_build_id],
        ).fetchdf()
        row_count = con.execute(
            "SELECT count(*) AS n FROM clean_snapshot_reference_factor_stage WHERE snapshot_build_id = ?",
            [snapshot_build_id],
        ).fetchone()[0]
    if not missing.empty:
        preview = ",".join(missing["stock_code"].astype(str).tolist())
        raise ValueError(f"missing reference_factor for stock_code: {preview}")
    return {"rows": int(row_count), "duration_seconds": _elapsed(started)}


def build_stock_ohlcv_from_staging_sql(
    storage: DuckDBStorage,
    snapshot_build_id: str,
    *,
    replace_existing: bool = True,
) -> dict[str, object]:
    ensure_clean_snapshot_staging_tables(storage)
    started = time.monotonic()
    with storage.connect() as con:
        daily_count = con.execute(
            """
            SELECT count(*) AS n
            FROM clean_snapshot_daily_raw_stage d
            JOIN clean_snapshot_selected_stock_stage s
              ON s.snapshot_build_id = d.snapshot_build_id
             AND s.stock_code = d.stock_code
            WHERE d.snapshot_build_id = ?
            """,
            [snapshot_build_id],
        ).fetchone()[0]
        if int(daily_count) == 0:
            raise ValueError("Tushare daily staging returned no rows for clean snapshot")
        con.execute("DROP TABLE IF EXISTS clean_snapshot_stock_ohlcv_final")
        con.execute(
            """
            CREATE TEMP TABLE clean_snapshot_stock_ohlcv_final AS
            WITH normalized_daily AS (
              SELECT
                d.*,
                CASE
                  WHEN d.open IS NULL OR d.high IS NULL OR d.low IS NULL OR d.close IS NULL THEN NULL
                  ELSE GREATEST(d.open, d.high, d.low, d.close)
                END AS canonical_high,
                CASE
                  WHEN d.open IS NULL OR d.high IS NULL OR d.low IS NULL OR d.close IS NULL THEN NULL
                  ELSE LEAST(d.open, d.high, d.low, d.close)
                END AS canonical_low,
                CASE
                  WHEN d.open IS NULL OR d.high IS NULL OR d.low IS NULL OR d.close IS NULL THEN FALSE
                  ELSE d.high < GREATEST(d.open, d.low, d.close)
                    OR d.low > LEAST(d.open, d.high, d.close)
                END AS ohlc_bound_repaired
              FROM clean_snapshot_daily_raw_stage d
              WHERE d.snapshot_build_id = ?
            )
            SELECT
              d.stock_code,
              d.trade_date,
              d.open * a.adj_factor / r.reference_adj_factor AS open,
              d.canonical_high * a.adj_factor / r.reference_adj_factor AS high,
              d.canonical_low * a.adj_factor / r.reference_adj_factor AS low,
              d.close * a.adj_factor / r.reference_adj_factor AS close,
              d.volume,
              d.amount,
              d.pct_chg,
              b.turnover,
              'tushare_qfq_rebased' AS source,
              now() AS fetched_at,
              ?::INTEGER AS source_priority,
              FALSE AS is_provisional,
              'validated_rebased' AS validation_status,
              NULL::TIMESTAMP AS vendor_update_time,
              d.ohlc_bound_repaired
            FROM normalized_daily d
            JOIN clean_snapshot_selected_stock_stage s
              ON s.snapshot_build_id = d.snapshot_build_id
             AND s.stock_code = d.stock_code
            JOIN clean_snapshot_adj_factor_stage a
              ON a.snapshot_build_id = d.snapshot_build_id
             AND a.stock_code = d.stock_code
             AND a.trade_date = d.trade_date
            JOIN clean_snapshot_reference_factor_stage r
              ON r.snapshot_build_id = d.snapshot_build_id
             AND r.stock_code = d.stock_code
            LEFT JOIN clean_snapshot_daily_basic_stage b
              ON b.snapshot_build_id = d.snapshot_build_id
             AND b.stock_code = d.stock_code
             AND b.trade_date = d.trade_date
            """,
            [snapshot_build_id, SOURCE_PRIORITY_PRIMARY],
        )
        final_count = con.execute("SELECT count(*) AS n FROM clean_snapshot_stock_ohlcv_final").fetchone()[0]
        ohlc_bound_repaired_count = con.execute(
            """
            SELECT count(*) AS n
            FROM clean_snapshot_stock_ohlcv_final
            WHERE ohlc_bound_repaired
            """
        ).fetchone()[0]
        if int(final_count) != int(daily_count):
            raise ValueError(f"missing adj_factor/reference rows: daily_rows={int(daily_count)}, final_rows={int(final_count)}")
        invalid_count = con.execute(
            """
            SELECT count(*) AS n
            FROM clean_snapshot_stock_ohlcv_final
            WHERE trade_date IS NULL
               OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
               OR high < low OR high < open OR high < close OR low > open OR low > close
               OR COALESCE(volume, 0) < 0 OR COALESCE(amount, 0) < 0
            """
        ).fetchone()[0]
        if int(invalid_count):
            raise ValueError(f"invalid clean stock_ohlcv rows from SQL transform: {int(invalid_count)}")
        qfq_sql_transform_duration = time.monotonic() - started
        write_started = time.monotonic()
        target_existing = con.execute("SELECT count(*) AS n FROM stock_ohlcv").fetchone()[0]
        if int(target_existing) == 0:
            write_mode = "bulk_insert"
        elif replace_existing:
            write_mode = "replace_insert"
        else:
            raise ValueError("stock_ohlcv target is not empty; replace_existing is required for controlled SQL replace/insert")
        if write_mode == "replace_insert":
            con.execute(
                """
                DELETE FROM stock_ohlcv
                USING clean_snapshot_stock_ohlcv_final f
                WHERE stock_ohlcv.stock_code = f.stock_code
                  AND stock_ohlcv.trade_date = f.trade_date
                """
            )
        con.execute(
            """
            INSERT INTO stock_ohlcv (
              stock_code, trade_date, open, high, low, close, volume, amount, pct_chg, turnover,
              source, fetched_at, source_priority, is_provisional, validation_status, vendor_update_time
            )
            SELECT
              stock_code, trade_date, open, high, low, close, volume, amount, pct_chg, turnover,
              source, fetched_at, source_priority, is_provisional, validation_status, vendor_update_time
            FROM clean_snapshot_stock_ohlcv_final
            """
        )
        stock_write_duration = time.monotonic() - write_started
    return {
        "rows": int(final_count),
        "write_mode": write_mode,
        "ohlc_bound_repaired_rows": int(ohlc_bound_repaired_count),
        "qfq_sql_transform_duration_seconds": round(qfq_sql_transform_duration, 3),
        "stock_write_duration_seconds": round(stock_write_duration, 3),
        "duration_seconds": _elapsed(started),
    }


def refresh_adj_factor_snapshot_from_staging(storage: DuckDBStorage, snapshot_build_id: str) -> dict[str, object]:
    started = time.monotonic()
    with storage.connect() as con:
        rows = con.execute(
            """
            SELECT count(*) AS n
            FROM clean_snapshot_adj_factor_stage
            WHERE snapshot_build_id = ?
            """,
            [snapshot_build_id],
        ).fetchone()[0]
        if int(rows) == 0:
            return {"rows": 0, "write_mode": "empty", "duration_seconds": _elapsed(started)}
        existing = con.execute("SELECT count(*) AS n FROM tushare_adj_factor_snapshot").fetchone()[0]
        write_mode = "bulk_insert" if int(existing) == 0 else "replace_insert"
        if write_mode == "replace_insert":
            con.execute(
                """
                DELETE FROM tushare_adj_factor_snapshot
                USING clean_snapshot_adj_factor_stage a
                WHERE a.snapshot_build_id = ?
                  AND tushare_adj_factor_snapshot.stock_code = a.stock_code
                  AND tushare_adj_factor_snapshot.trade_date = a.trade_date
                """,
                [snapshot_build_id],
            )
        con.execute(
            """
            INSERT INTO tushare_adj_factor_snapshot (
              ts_code, stock_code, trade_date, adj_factor, source, fetched_at, source_priority, validation_status
            )
            SELECT
              CASE WHEN ts_code IS NULL OR ts_code = '' THEN NULL ELSE ts_code END,
              stock_code,
              trade_date,
              adj_factor,
              'tushare_adj_factor',
              now(),
              ?::INTEGER,
              'validated'
            FROM clean_snapshot_adj_factor_stage
            WHERE snapshot_build_id = ?
            """,
            [SOURCE_PRIORITY_PRIMARY, snapshot_build_id],
        )
    return {"rows": int(rows), "write_mode": write_mode, "duration_seconds": _elapsed(started)}


def validate_clean_snapshot_sql(
    storage: DuckDBStorage,
    trade_dates: list[str],
    selected_stock_codes: list[str],
) -> dict[str, object]:
    started = time.monotonic()
    failures: list[str] = []
    warnings: list[str] = []
    expected_dates = [_date_obj(normalize_yyyymmdd(date)) for date in trade_dates]
    expected_codes = _normalize_code_list(selected_stock_codes)
    with storage.connect() as con:
        invalid_ohlcv_count = con.execute(
            """
            SELECT count(*) AS n
            FROM stock_ohlcv
            WHERE trade_date IS NULL
               OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
               OR high < low OR high < open OR high < close OR low > open OR low > close
               OR COALESCE(volume, 0) < 0 OR COALESCE(amount, 0) < 0
            """
        ).fetchone()[0]
        duplicate_count = con.execute(
            """
            SELECT count(*) AS n
            FROM (
              SELECT stock_code, trade_date, count(*) AS row_count
              FROM stock_ohlcv
              GROUP BY stock_code, trade_date
              HAVING count(*) > 1
            )
            """
        ).fetchone()[0]
        null_validation = con.execute("SELECT count(*) AS n FROM stock_ohlcv WHERE validation_status IS NULL").fetchone()[0]
        legacy_source_count = con.execute(
            """
            SELECT count(*) AS n
            FROM stock_ohlcv
            WHERE lower(COALESCE(source, '')) LIKE '%akshare%'
               OR lower(COALESCE(source, '')) LIKE '%ths%'
               OR lower(COALESCE(source, '')) LIKE '%eastmoney%'
               OR lower(COALESCE(source, '')) LIKE '%mootdx%'
            """
        ).fetchone()[0]
        invalid_source_count = con.execute(
            """
            SELECT count(*) AS n
            FROM stock_ohlcv
            WHERE COALESCE(source, '') NOT IN ('tushare_qfq', 'tushare_qfq_rebased')
            """
        ).fetchone()[0]
        latest_df = con.execute("SELECT max(trade_date) AS latest_trade_date FROM stock_ohlcv").fetchdf()
        latest_trade_date = None if latest_df.empty or pd.isna(latest_df.loc[0, "latest_trade_date"]) else pd.to_datetime(latest_df.loc[0, "latest_trade_date"]).strftime("%Y%m%d")
        sample_invalid_rows = con.execute(
            """
            SELECT stock_code, trade_date, open, high, low, close, volume, amount, source, validation_status
            FROM stock_ohlcv
            WHERE trade_date IS NULL
               OR open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL
               OR open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
               OR high < low OR high < open OR high < close OR low > open OR low > close
               OR COALESCE(volume, 0) < 0 OR COALESCE(amount, 0) < 0
            ORDER BY stock_code, trade_date
            LIMIT 20
            """
        ).fetchdf()
        source_df = con.execute("SELECT source, count(*) AS rows FROM stock_ohlcv GROUP BY source ORDER BY source").fetchdf()
        low_coverage_dates: list[str] = []
        severe_low_coverage_dates: list[str] = []
        if expected_dates and expected_codes:
            con.register("expected_dates", pd.DataFrame({"trade_date": expected_dates}))
            con.register("expected_codes", pd.DataFrame({"stock_code": expected_codes}))
            universe_rows = int(con.execute("SELECT count(*) AS n FROM all_a_stock_universe").fetchone()[0] or 0)
            low_df = con.execute(
                """
                WITH expected_universe AS (
                  SELECT e.trade_date, c.stock_code
                  FROM expected_dates e
                  CROSS JOIN expected_codes c
                  LEFT JOIN all_a_stock_universe u
                    ON u.stock_code = c.stock_code
                  WHERE ? = 0
                     OR (
                       u.stock_code IS NOT NULL
                       AND (u.list_date IS NULL OR u.list_date <= e.trade_date)
                       AND (u.delist_date IS NULL OR u.delist_date >= e.trade_date)
                     )
                ),
                daily_counts AS (
                  SELECT
                    e.trade_date,
                    count(DISTINCT e.stock_code) AS expected_count,
                    count(DISTINCT s.stock_code) AS covered_count
                  FROM expected_universe e
                  LEFT JOIN stock_ohlcv s
                    ON s.trade_date = e.trade_date
                   AND s.stock_code = e.stock_code
                  GROUP BY e.trade_date
                )
                SELECT trade_date, covered_count, expected_count
                FROM daily_counts
                WHERE expected_count > 0
                  AND covered_count::DOUBLE / NULLIF(expected_count::DOUBLE, 0) < 0.8
                ORDER BY trade_date
                """,
                [universe_rows],
            ).fetchdf()
            low_coverage_dates = pd.to_datetime(low_df["trade_date"]).dt.strftime("%Y%m%d").tolist() if not low_df.empty else []
            if not low_df.empty:
                severe = low_df[pd.to_numeric(low_df["covered_count"], errors="coerce") / pd.to_numeric(low_df["expected_count"], errors="coerce") < 0.4]
                severe_low_coverage_dates = pd.to_datetime(severe["trade_date"]).dt.strftime("%Y%m%d").tolist() if not severe.empty else []
        stock_rows = con.execute("SELECT count(*) AS n FROM stock_ohlcv").fetchone()[0]
        breadth_rows = con.execute("SELECT count(*) AS n FROM market_breadth_daily").fetchone()[0]
        sector_constituent_rows = con.execute("SELECT count(*) AS n FROM sector_constituents").fetchone()[0]
        sector_rows = con.execute("SELECT count(*) AS n FROM sector_ohlcv").fetchone()[0]
        feature_rows = con.execute("SELECT count(*) AS n FROM sector_features").fetchone()[0]
    if int(stock_rows) == 0:
        failures.append("stock_ohlcv is empty")
    if int(invalid_ohlcv_count):
        failures.append(f"stock_ohlcv has invalid OHLCV rows: {int(invalid_ohlcv_count)}")
    if int(duplicate_count):
        failures.append("stock_ohlcv has duplicate stock_code + trade_date rows")
    if int(null_validation):
        failures.append("stock_ohlcv validation_status contains nulls")
    if int(legacy_source_count):
        failures.append(f"stock_ohlcv contains legacy source rows: {int(legacy_source_count)}")
    if int(invalid_source_count):
        failures.append(f"stock_ohlcv contains non-clean Tushare source rows: {int(invalid_source_count)}")
    if expected_dates and latest_trade_date != pd.to_datetime(expected_dates[-1]).strftime("%Y%m%d"):
        failures.append(f"latest stock trade_date {latest_trade_date} does not match trade calendar {pd.to_datetime(expected_dates[-1]).strftime('%Y%m%d')}")
    if low_coverage_dates:
        warnings.append("universe trading coverage below 80% on " + ",".join(low_coverage_dates[:10]) + "; this can happen on suspension/no-trade dates")
    if severe_low_coverage_dates:
        failures.append("universe coverage below 40% on " + ",".join(severe_low_coverage_dates[:10]))
    if int(breadth_rows) == 0:
        failures.append("market_breadth_daily was not rebuilt")
    if int(sector_constituent_rows) > 0 and int(sector_rows) == 0:
        failures.append("sector_ohlcv was not rebuilt from target stock_ohlcv")
    if int(sector_rows) > 0 and int(feature_rows) == 0:
        failures.append("sector_features was not rebuilt after sector_ohlcv")
    source_distribution = dict(zip(source_df["source"].fillna("null").astype(str), source_df["rows"].astype(int), strict=False)) if not source_df.empty else {}
    return {
        "validation_status": "pass" if not failures else "failed",
        "invalid_ohlcv_count": int(invalid_ohlcv_count),
        "duplicate_stock_trade_date_count": int(duplicate_count),
        "null_validation_status_count": int(null_validation),
        "legacy_source_count": int(legacy_source_count),
        "invalid_source_count": int(invalid_source_count),
        "low_coverage_dates": low_coverage_dates,
        "severe_low_coverage_dates": severe_low_coverage_dates,
        "latest_trade_date": latest_trade_date,
        "sample_invalid_rows": sample_invalid_rows.to_dict("records"),
        "source_distribution": source_distribution,
        "failures": failures,
        "warnings": warnings,
        "duration_seconds": _elapsed(started),
    }


def rebuild_market_breadth_sql(
    storage: DuckDBStorage,
    start_date: str,
    end_date: str,
    *,
    mode: str = "full_market",
) -> dict[str, object]:
    started = time.monotonic()
    if mode not in {"full_market", "local_sample"}:
        raise ValueError("market breadth mode must be full_market or local_sample")
    start = _date_obj(normalize_yyyymmdd(start_date))
    end = _date_obj(normalize_yyyymmdd(end_date))
    calc_start = (pd.to_datetime(start) - pd.Timedelta(days=45)).date()
    with storage.connect() as con:
        con.execute("ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS coverage_mode TEXT")
        con.execute("ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS local_sample_internal_coverage DOUBLE")
        con.execute("ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS full_market_coverage_ratio DOUBLE")
        expected_count = None
        if mode == "full_market":
            expected_count = con.execute(
                """
                SELECT count(*) AS n
                FROM all_a_stock_universe
                WHERE COALESCE(list_status, 'active') = 'active'
                """
            ).fetchone()[0]
            if int(expected_count) == 0:
                return {"rows": 0, "failures": ["缺少全 A 股票池，不能计算全市场宽度。"], "duration_seconds": _elapsed(started)}
        con.execute("DROP TABLE IF EXISTS clean_snapshot_breadth_source")
        if mode == "full_market":
            con.execute(
                """
                CREATE TEMP TABLE clean_snapshot_breadth_source AS
                SELECT s.stock_code, s.trade_date, s.close, s.amount
                FROM stock_ohlcv s
                JOIN all_a_stock_universe u ON u.stock_code = s.stock_code
                WHERE COALESCE(u.list_status, 'active') = 'active'
                  AND s.trade_date BETWEEN ? AND ?
                """,
                [calc_start, end],
            )
        else:
            con.execute(
                """
                CREATE TEMP TABLE clean_snapshot_breadth_source AS
                SELECT stock_code, trade_date, close, amount
                FROM stock_ohlcv
                WHERE trade_date BETWEEN ? AND ?
                """,
                [calc_start, end],
            )
        source_rows = con.execute("SELECT count(*) AS n FROM clean_snapshot_breadth_source").fetchone()[0]
        if int(source_rows) == 0:
            target = "全 A 股票池" if mode == "full_market" else "本地股票样本"
            return {"rows": 0, "failures": [f"缺少{target}个股行情，无法计算宽度"], "duration_seconds": _elapsed(started)}
        con.execute("DROP TABLE IF EXISTS clean_snapshot_market_breadth_final")
        con.execute(
            """
            CREATE TEMP TABLE clean_snapshot_market_breadth_final AS
            WITH stock_window AS (
              SELECT
                stock_code,
                trade_date,
                close,
                amount,
                close / NULLIF(lag(close) OVER (PARTITION BY stock_code ORDER BY trade_date), 0) - 1 AS daily_ret,
                CASE
                  WHEN count(close) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) >= 10
                  THEN avg(close) OVER (PARTITION BY stock_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
                  ELSE NULL
                END AS ma20
              FROM clean_snapshot_breadth_source
            ),
            daily AS (
              SELECT
                trade_date,
                sum(CASE WHEN daily_ret > 0 THEN 1 ELSE 0 END)::INTEGER AS up_count,
                sum(CASE WHEN daily_ret < 0 THEN 1 ELSE 0 END)::INTEGER AS down_count,
                sum(CASE WHEN daily_ret = 0 THEN 1 ELSE 0 END)::INTEGER AS unchanged_count,
                sum(CASE WHEN daily_ret >= 0.098 THEN 1 ELSE 0 END)::INTEGER AS limit_up_count,
                sum(CASE WHEN daily_ret <= -0.098 THEN 1 ELSE 0 END)::INTEGER AS limit_down_count,
                sum(CASE WHEN ma20 IS NOT NULL AND close > ma20 THEN 1 ELSE 0 END)::INTEGER AS above_ma20_count,
                sum(CASE WHEN ma20 IS NOT NULL THEN 1 ELSE 0 END)::INTEGER AS ma20_valid_count,
                count(DISTINCT stock_code)::INTEGER AS total_count,
                sum(CASE WHEN daily_ret IS NOT NULL THEN 1 ELSE 0 END)::INTEGER AS effective_count,
                sum(COALESCE(amount, 0)) AS amount_total
              FROM stock_window
              GROUP BY trade_date
            ),
            scored AS (
              SELECT
                trade_date,
                up_count,
                down_count,
                unchanged_count,
                limit_up_count,
                limit_down_count,
                above_ma20_count,
                (ma20_valid_count - above_ma20_count)::INTEGER AS below_ma20_count,
                total_count,
                effective_count,
                ma20_valid_count,
                ?::INTEGER AS expected_count,
                effective_count::DOUBLE / NULLIF(?::DOUBLE, 0) AS full_market_coverage_ratio,
                effective_count::DOUBLE / NULLIF(total_count::DOUBLE, 0) AS local_sample_internal_coverage,
                up_count::DOUBLE / NULLIF(effective_count::DOUBLE, 0) AS up_ratio,
                above_ma20_count::DOUBLE / NULLIF(ma20_valid_count::DOUBLE, 0) AS above_ma20_ratio,
                amount_total,
                (amount_total - avg(amount_total) OVER (ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW))
                  / NULLIF(stddev_pop(amount_total) OVER (ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW), 0) AS amount_z_20d
              FROM daily
            )
            SELECT
              trade_date,
              up_count,
              down_count,
              unchanged_count,
              limit_up_count,
              limit_down_count,
              above_ma20_count,
              below_ma20_count,
              total_count,
              effective_count,
              ma20_valid_count,
              CASE WHEN ? = 'full_market' THEN expected_count ELSE NULL END AS expected_count,
              CASE WHEN ? = 'full_market' THEN full_market_coverage_ratio ELSE NULL END AS coverage_ratio,
              ? AS coverage_mode,
              CASE WHEN ? = 'local_sample' THEN local_sample_internal_coverage ELSE NULL END AS local_sample_internal_coverage,
              CASE WHEN ? = 'full_market' THEN full_market_coverage_ratio ELSE NULL END AS full_market_coverage_ratio,
              ? AS breadth_mode,
              up_ratio,
              above_ma20_ratio,
              amount_total,
              CASE
                WHEN count(amount_total) OVER (ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) >= 10 THEN amount_z_20d
                ELSE NULL
              END AS amount_z_20d,
              CASE
                WHEN ? = 'full_market' AND expected_count IS NOT NULL AND full_market_coverage_ratio >= 0.8 AND effective_count >= 2500 THEN 'full_market'
                WHEN ? = 'full_market' AND full_market_coverage_ratio >= 0.4 THEN 'partial_sample'
                WHEN ? = 'full_market' THEN 'insufficient'
                WHEN ? = 'local_sample' AND effective_count >= 500 THEN 'local_sample'
                WHEN ? = 'local_sample' THEN 'insufficient'
                ELSE 'unknown'
              END AS coverage_level,
              '' AS coverage_warning,
              CASE WHEN ? = 'full_market' THEN 'tushare_stock_ohlcv_width' ELSE 'local_stock_sample' END AS source,
              now() AS fetched_at,
              CASE WHEN ? = 'full_market' THEN 0 ELSE 50 END AS source_priority,
              ? <> 'full_market' AS is_provisional,
              CASE
                WHEN ? = 'full_market' AND expected_count IS NOT NULL AND full_market_coverage_ratio >= 0.8 AND effective_count >= 2500 THEN 'validated'
                WHEN ? = 'full_market' AND full_market_coverage_ratio >= 0.4 THEN 'coverage_partial_sample'
                WHEN ? = 'full_market' THEN 'coverage_insufficient'
                WHEN ? = 'local_sample' AND effective_count >= 500 THEN 'coverage_local_sample'
                ELSE 'coverage_insufficient'
              END AS validation_status,
              NULL::TIMESTAMP AS vendor_update_time
            FROM scored
            WHERE trade_date BETWEEN ? AND ?
            """,
            [int(expected_count or 0), int(expected_count or 0), *([mode] * 18), start, end],
        )
        con.execute("DELETE FROM market_breadth_daily WHERE trade_date BETWEEN ? AND ? AND breadth_mode = ?", [start, end, mode])
        con.execute(
            """
            INSERT INTO market_breadth_daily (
              trade_date, up_count, down_count, unchanged_count, limit_up_count, limit_down_count,
              above_ma20_count, below_ma20_count, total_count, effective_count, ma20_valid_count,
              expected_count, coverage_ratio, coverage_mode, local_sample_internal_coverage,
              full_market_coverage_ratio, breadth_mode, up_ratio, above_ma20_ratio, amount_total,
              amount_z_20d, coverage_level, coverage_warning, source, fetched_at, source_priority,
              is_provisional, validation_status, vendor_update_time
            )
            SELECT
              trade_date, up_count, down_count, unchanged_count, limit_up_count, limit_down_count,
              above_ma20_count, below_ma20_count, total_count, effective_count, ma20_valid_count,
              expected_count, coverage_ratio, coverage_mode, local_sample_internal_coverage,
              full_market_coverage_ratio, breadth_mode, up_ratio, above_ma20_ratio, amount_total,
              amount_z_20d, coverage_level, coverage_warning, source, fetched_at, source_priority,
              is_provisional, validation_status, vendor_update_time
            FROM clean_snapshot_market_breadth_final
            """
        )
        rows = con.execute("SELECT count(*) AS n FROM clean_snapshot_market_breadth_final").fetchone()[0]
    return {"rows": int(rows), "failures": [], "duration_seconds": _elapsed(started)}


def rebuild_sector_ohlcv_sql(storage: DuckDBStorage, start_date: str, end_date: str) -> dict[str, object]:
    started = time.monotonic()
    start = _date_obj(normalize_yyyymmdd(start_date))
    end = _date_obj(normalize_yyyymmdd(end_date))
    calc_start = (pd.to_datetime(start) - pd.Timedelta(days=15)).date()
    with storage.connect() as con:
        sector_count = con.execute(
            """
            SELECT count(DISTINCT m.sector_id) AS n
            FROM sector_meta m
            JOIN sector_constituents c ON c.sector_id = m.sector_id
            WHERE m.sector_type = 'industry'
              AND COALESCE(m.is_active, TRUE)
            """
        ).fetchone()[0]
        if int(sector_count) == 0:
            return {"rows": 0, "sector_count": 0, "warnings": ["no industry sectors available"], "status": "pass", "duration_seconds": _elapsed(started)}
        con.execute("DROP TABLE IF EXISTS clean_snapshot_sector_ohlcv_final")
        con.execute(
            """
            CREATE TEMP TABLE clean_snapshot_sector_ohlcv_final AS
            WITH member_prices AS (
              SELECT
                c.sector_id,
                s.stock_code,
                s.trade_date,
                s.open,
                s.high,
                s.low,
                s.close,
                s.volume,
                s.amount,
                lag(s.close) OVER (PARTITION BY s.stock_code ORDER BY s.trade_date) AS prev_close
              FROM stock_ohlcv s
              JOIN sector_constituents c ON c.stock_code = s.stock_code
              JOIN sector_meta m ON m.sector_id = c.sector_id
              WHERE m.sector_type = 'industry'
                AND COALESCE(m.is_active, TRUE)
                AND s.trade_date BETWEEN ? AND ?
            ),
            sector_daily AS (
              SELECT
                sector_id,
                trade_date,
                avg(CASE WHEN prev_close > 0 THEN open / prev_close - 1 ELSE 0 END) AS open_ret,
                avg(CASE WHEN prev_close > 0 THEN high / prev_close - 1 ELSE 0 END) AS high_ret,
                avg(CASE WHEN prev_close > 0 THEN low / prev_close - 1 ELSE 0 END) AS low_ret,
                avg(CASE WHEN prev_close > 0 THEN close / prev_close - 1 ELSE 0 END) AS close_ret,
                sum(COALESCE(volume, 0)) AS volume,
                sum(COALESCE(amount, 0)) AS amount
              FROM member_prices
              GROUP BY sector_id, trade_date
            ),
            close_path AS (
              SELECT
                sector_id,
                trade_date,
                open_ret,
                high_ret,
                low_ret,
                close_ret,
                volume,
                amount,
                1000.0 * exp(sum(ln(GREATEST(1 + COALESCE(close_ret, 0), 0.000001))) OVER (
                  PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                )) AS close
              FROM sector_daily
            ),
            priced AS (
              SELECT
                sector_id,
                trade_date,
                COALESCE(lag(close) OVER (PARTITION BY sector_id ORDER BY trade_date), 1000.0) AS prev_sector_close,
                open_ret,
                high_ret,
                low_ret,
                close,
                volume,
                amount
              FROM close_path
            )
            SELECT
              sector_id,
              trade_date,
              GREATEST(prev_sector_close * (1 + COALESCE(open_ret, 0)), 0.000001) AS open,
              GREATEST(prev_sector_close * (1 + COALESCE(high_ret, 0)), 0.000001) AS high,
              GREATEST(prev_sector_close * (1 + COALESCE(low_ret, 0)), 0.000001) AS low,
              close,
              volume,
              amount,
              close / NULLIF(prev_sector_close, 0) - 1 AS pct_chg,
              NULL::DOUBLE AS turnover,
              'tushare_local_aggregate' AS source,
              now() AS fetched_at,
              0 AS source_priority,
              FALSE AS is_provisional,
              'local_aggregate' AS validation_status,
              NULL::TIMESTAMP AS vendor_update_time
            FROM priced
            WHERE trade_date BETWEEN ? AND ?
            """,
            [calc_start, end, start, end],
        )
        con.execute(
            """
            UPDATE clean_snapshot_sector_ohlcv_final
            SET
              high = GREATEST(high, open, low, close),
              low = LEAST(low, open, high, close)
            """
        )
        con.execute("DELETE FROM sector_ohlcv USING clean_snapshot_sector_ohlcv_final f WHERE sector_ohlcv.sector_id = f.sector_id AND sector_ohlcv.trade_date = f.trade_date")
        con.execute(
            """
            INSERT INTO sector_ohlcv (
              sector_id, trade_date, open, high, low, close, volume, amount, pct_chg, turnover,
              source, fetched_at, source_priority, is_provisional, validation_status, vendor_update_time
            )
            SELECT
              sector_id, trade_date, open, high, low, close, volume, amount, pct_chg, turnover,
              source, fetched_at, source_priority, is_provisional, validation_status, vendor_update_time
            FROM clean_snapshot_sector_ohlcv_final
            """
        )
        rows = con.execute("SELECT count(*) AS n FROM clean_snapshot_sector_ohlcv_final").fetchone()[0]
    return {"rows": int(rows), "sector_count": int(sector_count), "status": "pass", "failures": [], "duration_seconds": _elapsed(started)}


def rebuild_sector_features_sql(storage: DuckDBStorage, start_date: str, end_date: str) -> dict[str, object]:
    started = time.monotonic()
    start = _date_obj(normalize_yyyymmdd(start_date))
    end = _date_obj(normalize_yyyymmdd(end_date))
    calc_start = (pd.to_datetime(start) - pd.Timedelta(days=45)).date()
    feature_version = settings.default_feature_version
    with storage.connect() as con:
        con.execute("DROP TABLE IF EXISTS clean_snapshot_sector_features_final")
        con.execute(
            """
            CREATE TEMP TABLE clean_snapshot_sector_features_final AS
            WITH base AS (
              SELECT
                sector_id,
                trade_date,
                open,
                high,
                low,
                close,
                amount,
                close / NULLIF(lag(close) OVER (PARTITION BY sector_id ORDER BY trade_date), 0) - 1 AS ret_1d,
                open / NULLIF(lag(close) OVER (PARTITION BY sector_id ORDER BY trade_date), 0) - 1 AS gap_1d,
                close / NULLIF(open, 0) - 1 AS intraday_ret
              FROM sector_ohlcv
              WHERE trade_date BETWEEN ? AND ?
            ),
            sector_roll AS (
              SELECT
                *,
                close / NULLIF(lag(close, 5) OVER (PARTITION BY sector_id ORDER BY trade_date), 0) - 1 AS ret_5d,
                close / NULLIF(lag(close, 20) OVER (PARTITION BY sector_id ORDER BY trade_date), 0) - 1 AS ret_20d,
                CASE
                  WHEN count(ret_1d) OVER (PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) >= 10
                  THEN stddev_pop(ret_1d) OVER (PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) * sqrt(20.0)
                  ELSE NULL
                END AS vol_20d,
                CASE
                  WHEN count(amount) OVER (PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) >= 10
                  THEN (amount - avg(amount) OVER (PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW))
                    / NULLIF(stddev_pop(amount) OVER (PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW), 0)
                  ELSE NULL
                END AS amount_z_20d,
                CASE
                  WHEN count(close) OVER (PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) >= 10
                  THEN close / NULLIF(max(close) OVER (PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW), 0) - 1
                  ELSE NULL
                END AS drawdown_20d,
                CASE
                  WHEN count(close) OVER (PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) >= 10
                  THEN avg(close) OVER (PARTITION BY sector_id ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
                  ELSE NULL
                END AS ma20
              FROM base
            ),
            benchmark AS (
              SELECT
                trade_date,
                avg(ret_1d) AS benchmark_ret_1d
              FROM base
              GROUP BY trade_date
            ),
            benchmark_roll AS (
              SELECT
                trade_date,
                CASE
                  WHEN count(benchmark_ret_1d) OVER (ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) >= 20
                  THEN exp(sum(ln(GREATEST(1 + COALESCE(benchmark_ret_1d, 0), 0.000001))) OVER (ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)) - 1
                  ELSE NULL
                END AS benchmark_ret_20d
              FROM benchmark
            ),
            enriched AS (
              SELECT
                s.sector_id,
                s.trade_date,
                s.ret_1d,
                s.ret_5d,
                s.ret_20d,
                s.vol_20d,
                s.amount_z_20d,
                s.ret_20d - b.benchmark_ret_20d AS rs_20d,
                s.drawdown_20d,
                s.ma20 / NULLIF(lag(s.ma20, 5) OVER (PARTITION BY s.sector_id ORDER BY s.trade_date), 0) - 1 AS ma20_slope,
                s.gap_1d,
                s.intraday_ret,
                s.amount_z_20d AS amount_shock_z
              FROM sector_roll s
              LEFT JOIN benchmark_roll b ON b.trade_date = s.trade_date
            )
            SELECT
              sector_id,
              trade_date,
              ret_1d,
              ret_5d,
              ret_20d,
              vol_20d,
              amount_z_20d,
              rs_20d,
              drawdown_20d,
              ma20_slope,
              ? AS feature_version,
              'all' AS feature_scope_id,
              'all' AS feature_scope_type,
              gap_1d,
              intraday_ret,
              amount_shock_z
            FROM enriched
            WHERE trade_date BETWEEN ? AND ?
            """,
            [calc_start, end, feature_version, start, end],
        )
        con.execute(
            """
            DELETE FROM sector_features
            USING clean_snapshot_sector_features_final f
            WHERE sector_features.sector_id = f.sector_id
              AND sector_features.trade_date = f.trade_date
              AND sector_features.feature_version = f.feature_version
              AND sector_features.feature_scope_id = f.feature_scope_id
            """
        )
        con.execute(
            """
            INSERT INTO sector_features (
              sector_id, trade_date, ret_1d, ret_5d, ret_20d, vol_20d, amount_z_20d,
              rs_20d, drawdown_20d, ma20_slope, feature_version, feature_scope_id,
              feature_scope_type, gap_1d, intraday_ret, amount_shock_z
            )
            SELECT
              sector_id, trade_date, ret_1d, ret_5d, ret_20d, vol_20d, amount_z_20d,
              rs_20d, drawdown_20d, ma20_slope, feature_version, feature_scope_id,
              feature_scope_type, gap_1d, intraday_ret, amount_shock_z
            FROM clean_snapshot_sector_features_final
            """
        )
        rows = con.execute("SELECT count(*) AS n FROM clean_snapshot_sector_features_final").fetchone()[0]
    return {"rows": int(rows), "duration_seconds": _elapsed(started)}
