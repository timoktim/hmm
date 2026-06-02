from __future__ import annotations

import json
import hashlib
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable
import uuid

import duckdb
import pandas as pd

from src.config import settings


_DB_WRITE_LOCK = threading.RLock()


@contextmanager
def _schema_file_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        handle.close()


class DuckDBStorage:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or settings.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> duckdb.DuckDBPyConnection:
        con = duckdb.connect(str(self.db_path))
        con.execute("SET timezone='Asia/Shanghai'")
        return con

    def _migrate_sector_features_scope(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("ALTER TABLE sector_features ADD COLUMN IF NOT EXISTS feature_scope_id TEXT DEFAULT 'all'")
        con.execute("ALTER TABLE sector_features ADD COLUMN IF NOT EXISTS feature_scope_type TEXT DEFAULT 'all'")
        con.execute("UPDATE sector_features SET feature_scope_id = 'all' WHERE feature_scope_id IS NULL")
        con.execute("UPDATE sector_features SET feature_scope_type = 'all' WHERE feature_scope_type IS NULL")
        constraints = con.execute(
            """
            SELECT constraint_text
            FROM duckdb_constraints()
            WHERE table_name = 'sector_features'
              AND constraint_type = 'PRIMARY KEY'
            """
        ).fetchdf()
        if not constraints.empty and constraints["constraint_text"].astype(str).str.contains("feature_scope_id").any():
            return
        con.execute("DROP TABLE IF EXISTS sector_features_scoped_migration")
        con.execute(
            """
            CREATE TABLE sector_features_scoped_migration (
              sector_id VARCHAR,
              trade_date DATE,
              ret_1d DOUBLE,
              ret_5d DOUBLE,
              ret_20d DOUBLE,
              vol_20d DOUBLE,
              amount_z_20d DOUBLE,
              rs_20d DOUBLE,
              drawdown_20d DOUBLE,
              ma20_slope DOUBLE,
              feature_version VARCHAR,
              feature_scope_id TEXT DEFAULT 'all',
              feature_scope_type TEXT DEFAULT 'all',
              PRIMARY KEY (sector_id, trade_date, feature_version, feature_scope_id)
            )
            """
        )
        con.execute(
            """
            INSERT INTO sector_features_scoped_migration
            SELECT sector_id, trade_date, ret_1d, ret_5d, ret_20d, vol_20d,
                   amount_z_20d, rs_20d, drawdown_20d, ma20_slope, feature_version,
                   COALESCE(feature_scope_id, 'all'), COALESCE(feature_scope_type, 'all')
            FROM sector_features
            """
        )
        con.execute("DROP TABLE sector_features")
        con.execute("ALTER TABLE sector_features_scoped_migration RENAME TO sector_features")

    def _migrate_market_breadth_daily_key(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS breadth_mode TEXT")
        con.execute("UPDATE market_breadth_daily SET breadth_mode = 'local_sample' WHERE breadth_mode IS NULL")
        constraints = con.execute(
            """
            SELECT constraint_text
            FROM duckdb_constraints()
            WHERE table_name = 'market_breadth_daily'
              AND constraint_type = 'PRIMARY KEY'
            """
        ).fetchdf()
        if not constraints.empty and constraints["constraint_text"].astype(str).str.contains("breadth_mode").any():
            return
        con.execute("DROP TABLE IF EXISTS market_breadth_daily_mode_migration")
        con.execute(
            """
            CREATE TABLE market_breadth_daily_mode_migration (
              trade_date DATE,
              up_count INTEGER,
              down_count INTEGER,
              unchanged_count INTEGER,
              limit_up_count INTEGER,
              limit_down_count INTEGER,
              above_ma20_count INTEGER,
              below_ma20_count INTEGER,
              total_count INTEGER,
              effective_count INTEGER,
              ma20_valid_count INTEGER,
              expected_count INTEGER,
              coverage_ratio DOUBLE,
              breadth_mode TEXT,
              up_ratio DOUBLE,
              above_ma20_ratio DOUBLE,
              amount_total DOUBLE,
              amount_z_20d DOUBLE,
              coverage_level TEXT,
              coverage_warning TEXT,
              source TEXT,
              fetched_at TIMESTAMP,
              PRIMARY KEY (trade_date, breadth_mode)
            )
            """
        )
        con.execute(
            """
            INSERT INTO market_breadth_daily_mode_migration
            SELECT trade_date, up_count, down_count, unchanged_count, limit_up_count,
                   limit_down_count, above_ma20_count, below_ma20_count, total_count,
                   effective_count, ma20_valid_count, expected_count, coverage_ratio,
                   COALESCE(breadth_mode, 'local_sample'), up_ratio, above_ma20_ratio,
                   amount_total, amount_z_20d, coverage_level, coverage_warning,
                   source, fetched_at
            FROM (
              SELECT *,
                     row_number() OVER (
                       PARTITION BY trade_date, COALESCE(breadth_mode, 'local_sample')
                       ORDER BY fetched_at DESC NULLS LAST
                     ) AS rn
              FROM market_breadth_daily
            )
            WHERE rn = 1
            """
        )
        con.execute("DROP TABLE market_breadth_daily")
        con.execute("ALTER TABLE market_breadth_daily_mode_migration RENAME TO market_breadth_daily")

    def init_schema(self) -> None:
        digest = hashlib.sha1(str(self.db_path.resolve()).encode("utf-8")).hexdigest()[:16]
        lock_path = Path(tempfile.gettempdir()) / f"a_share_hmm_schema_{digest}.lock"
        for attempt in range(3):
            try:
                with _DB_WRITE_LOCK, _schema_file_lock(lock_path), self.connect() as con:
                    self._init_schema_with_connection(con)
                return
            except duckdb.TransactionException:
                if attempt == 2:
                    raise
                time.sleep(0.2 * (attempt + 1))

    def _init_schema_with_connection(self, con: duckdb.DuckDBPyConnection) -> None:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sector_meta (
                  sector_id VARCHAR PRIMARY KEY,
                  sector_type VARCHAR,
                  sector_name VARCHAR,
                  source VARCHAR,
                  last_update TIMESTAMP,
                  is_active BOOLEAN DEFAULT TRUE,
                  active_checked_at TIMESTAMP
                );
                """
            )
            for column_sql in [
                "ALTER TABLE sector_meta ADD COLUMN IF NOT EXISTS is_active BOOLEAN",
                "ALTER TABLE sector_meta ADD COLUMN IF NOT EXISTS active_checked_at TIMESTAMP",
            ]:
                con.execute(column_sql)
            con.execute("UPDATE sector_meta SET is_active = TRUE WHERE is_active IS NULL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sector_ohlcv (
                  sector_id VARCHAR,
                  trade_date DATE,
                  open DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  close DOUBLE,
                  volume DOUBLE,
                  amount DOUBLE,
                  pct_chg DOUBLE,
                  turnover DOUBLE,
                  source VARCHAR,
                  fetched_at TIMESTAMP,
                  PRIMARY KEY (sector_id, trade_date)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sector_constituents (
                  sector_id VARCHAR,
                  stock_code VARCHAR,
                  stock_name VARCHAR,
                  in_sector_date DATE,
                  source VARCHAR,
                  fetched_at TIMESTAMP,
                  PRIMARY KEY (sector_id, stock_code)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_ohlcv (
                  stock_code VARCHAR,
                  trade_date DATE,
                  open DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  close DOUBLE,
                  volume DOUBLE,
                  amount DOUBLE,
                  pct_chg DOUBLE,
                  turnover DOUBLE,
                  source VARCHAR,
                  fetched_at TIMESTAMP,
                  PRIMARY KEY (stock_code, trade_date)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS market_benchmark_ohlcv (
                  benchmark_id VARCHAR,
                  trade_date DATE,
                  open DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  close DOUBLE,
                  volume DOUBLE,
                  amount DOUBLE,
                  pct_chg DOUBLE,
                  turnover DOUBLE,
                  source VARCHAR,
                  fetched_at TIMESTAMP,
                  PRIMARY KEY (benchmark_id, trade_date)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS market_index_ohlcv (
                  index_code TEXT,
                  index_name TEXT,
                  trade_date DATE,
                  open DOUBLE,
                  high DOUBLE,
                  low DOUBLE,
                  close DOUBLE,
                  volume DOUBLE,
                  amount DOUBLE,
                  pct_chg DOUBLE,
                  source TEXT,
                  fetched_at TIMESTAMP,
                  PRIMARY KEY (index_code, trade_date)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS market_breadth_daily (
                  trade_date DATE,
                  up_count INTEGER,
                  down_count INTEGER,
                  unchanged_count INTEGER,
                  limit_up_count INTEGER,
                  limit_down_count INTEGER,
                  above_ma20_count INTEGER,
                  below_ma20_count INTEGER,
                  total_count INTEGER,
                  effective_count INTEGER,
                  ma20_valid_count INTEGER,
                  expected_count INTEGER,
                  coverage_ratio DOUBLE,
                  breadth_mode TEXT,
                  up_ratio DOUBLE,
                  above_ma20_ratio DOUBLE,
                  amount_total DOUBLE,
                  amount_z_20d DOUBLE,
                  coverage_level TEXT,
                  coverage_warning TEXT,
                  source TEXT,
                  fetched_at TIMESTAMP,
                  PRIMARY KEY (trade_date, breadth_mode)
                );
                """
            )
            for column_sql in [
                "ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS coverage_level TEXT",
                "ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS coverage_warning TEXT",
                "ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS effective_count INTEGER",
                "ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS ma20_valid_count INTEGER",
                "ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS expected_count INTEGER",
                "ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS coverage_ratio DOUBLE",
                "ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS breadth_mode TEXT",
            ]:
                con.execute(column_sql)
            self._migrate_market_breadth_daily_key(con)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS all_a_stock_universe (
                  stock_code TEXT PRIMARY KEY,
                  stock_name TEXT,
                  exchange TEXT,
                  list_status TEXT,
                  is_st BOOLEAN,
                  list_date DATE,
                  delist_date DATE,
                  source TEXT,
                  fetched_at TIMESTAMP
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS market_regime_runs (
                  run_id TEXT PRIMARY KEY,
                  n_states INTEGER,
                  train_start DATE,
                  train_end DATE,
                  feature_version TEXT,
                  model_path TEXT,
                  scaler_path TEXT,
                  created_at TIMESTAMP,
                  metrics_json TEXT
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS market_regime_daily (
                  run_id TEXT,
                  trade_date DATE,
                  state_id INTEGER,
                  state_label TEXT,
                  prob_risk_on DOUBLE,
                  prob_neutral DOUBLE,
                  prob_risk_off DOUBLE,
                  next_state_probs_json TEXT,
                  feature_version TEXT,
                  created_at TIMESTAMP,
                  PRIMARY KEY (run_id, trade_date)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sector_features (
                  sector_id VARCHAR,
                  trade_date DATE,
                  ret_1d DOUBLE,
                  ret_5d DOUBLE,
                  ret_20d DOUBLE,
                  vol_20d DOUBLE,
                  amount_z_20d DOUBLE,
                  rs_20d DOUBLE,
                  drawdown_20d DOUBLE,
                  ma20_slope DOUBLE,
                  feature_version VARCHAR,
                  feature_scope_id TEXT DEFAULT 'all',
                  feature_scope_type TEXT DEFAULT 'all',
                  PRIMARY KEY (sector_id, trade_date, feature_version, feature_scope_id)
                );
                """
            )
            self._migrate_sector_features_scope(con)
            for column_sql in [
                "ALTER TABLE sector_features ADD COLUMN IF NOT EXISTS gap_1d DOUBLE",
                "ALTER TABLE sector_features ADD COLUMN IF NOT EXISTS intraday_ret DOUBLE",
                "ALTER TABLE sector_features ADD COLUMN IF NOT EXISTS amount_shock_z DOUBLE",
            ]:
                con.execute(column_sql)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS model_runs (
                  run_id VARCHAR PRIMARY KEY,
                  model_type VARCHAR,
                  n_states INTEGER,
                  train_start DATE,
                  train_end DATE,
                  feature_version VARCHAR,
                  model_path VARCHAR,
                  scaler_path VARCHAR,
                  universe_id TEXT,
                  scope_type TEXT DEFAULT 'all',
                  include_custom_baskets BOOLEAN DEFAULT TRUE,
                  feature_scope_id TEXT DEFAULT 'all',
                  feature_scope_type TEXT DEFAULT 'all',
                  created_at TIMESTAMP,
                  metrics_json VARCHAR
                );
                """
            )
            for column_sql in [
                "ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS universe_id TEXT",
                "ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS scope_type TEXT DEFAULT 'all'",
                "ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS include_custom_baskets BOOLEAN DEFAULT TRUE",
                "ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS feature_scope_id TEXT DEFAULT 'all'",
                "ALTER TABLE model_runs ADD COLUMN IF NOT EXISTS feature_scope_type TEXT DEFAULT 'all'",
            ]:
                con.execute(column_sql)
            con.execute("UPDATE model_runs SET scope_type = 'all' WHERE scope_type IS NULL")
            con.execute("UPDATE model_runs SET include_custom_baskets = TRUE WHERE include_custom_baskets IS NULL")
            con.execute("UPDATE model_runs SET feature_scope_id = COALESCE(feature_scope_id, CASE WHEN universe_id IS NULL THEN 'all' ELSE universe_id END)")
            con.execute("UPDATE model_runs SET feature_scope_type = COALESCE(feature_scope_type, scope_type, 'all')")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sector_state_daily (
                  run_id VARCHAR,
                  sector_id VARCHAR,
                  trade_date DATE,
                  state_id INTEGER,
                  state_label VARCHAR,
                  prob_trend_up DOUBLE,
                  prob_neutral DOUBLE,
                  prob_risk_off DOUBLE,
                  next_state_probs_json VARCHAR,
                  state_source VARCHAR DEFAULT 'in_sample_display',
                  PRIMARY KEY (run_id, sector_id, trade_date)
                );
                """
            )
            con.execute("ALTER TABLE sector_state_daily ADD COLUMN IF NOT EXISTS state_source VARCHAR DEFAULT 'in_sample_display'")
            con.execute("UPDATE sector_state_daily SET state_source = 'in_sample_display' WHERE state_source IS NULL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS walk_forward_cache_runs (
                  cache_key VARCHAR PRIMARY KEY,
                  n_states INTEGER,
                  train_window_days INTEGER,
                  retrain_frequency VARCHAR,
                  feature_version VARCHAR,
                  start_date DATE,
                  end_date DATE,
                  params_json TEXT,
                  params_hash VARCHAR,
                  universe_id VARCHAR,
                  scope_type VARCHAR,
                  include_custom_baskets BOOLEAN,
                  rebalance_days INTEGER,
                  state_date_mode VARCHAR,
                  feature_scope_id VARCHAR,
                  signal_count INTEGER,
                  row_count INTEGER,
                  created_at TIMESTAMP
                );
                """
            )
            for column_sql in [
                "ALTER TABLE walk_forward_cache_runs ADD COLUMN IF NOT EXISTS params_json TEXT",
                "ALTER TABLE walk_forward_cache_runs ADD COLUMN IF NOT EXISTS params_hash VARCHAR",
                "ALTER TABLE walk_forward_cache_runs ADD COLUMN IF NOT EXISTS universe_id VARCHAR",
                "ALTER TABLE walk_forward_cache_runs ADD COLUMN IF NOT EXISTS scope_type VARCHAR",
                "ALTER TABLE walk_forward_cache_runs ADD COLUMN IF NOT EXISTS include_custom_baskets BOOLEAN",
                "ALTER TABLE walk_forward_cache_runs ADD COLUMN IF NOT EXISTS rebalance_days INTEGER",
                "ALTER TABLE walk_forward_cache_runs ADD COLUMN IF NOT EXISTS state_date_mode VARCHAR",
                "ALTER TABLE walk_forward_cache_runs ADD COLUMN IF NOT EXISTS feature_scope_id VARCHAR",
            ]:
                con.execute(column_sql)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS walk_forward_state_cache (
                  cache_key VARCHAR,
                  sector_id VARCHAR,
                  trade_date DATE,
                  state_id INTEGER,
                  state_label VARCHAR,
                  prob_trend_up DOUBLE,
                  prob_neutral DOUBLE,
                  prob_risk_off DOUBLE,
                  next_state_probs_json VARCHAR,
                  train_start DATE,
                  train_end DATE,
                  max_observation_date_used DATE,
                  probability_type VARCHAR,
                  state_source VARCHAR,
                  PRIMARY KEY (cache_key, sector_id, trade_date)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS causal_cache_run_linkage (
                  linkage_id TEXT PRIMARY KEY,
                  cache_key TEXT,
                  causal_cache_id TEXT,
                  resolved_run_id TEXT,
                  model_run_id TEXT,
                  causal_evidence_id TEXT,
                  linkage_status TEXT,
                  linkage_confidence DOUBLE,
                  linkage_method TEXT,
                  feature_scope_id TEXT,
                  universe_id TEXT,
                  scope_type TEXT,
                  feature_version TEXT,
                  n_states INTEGER,
                  cache_start_date DATE,
                  cache_end_date DATE,
                  model_train_start DATE,
                  model_train_end DATE,
                  coverage_ratio DOUBLE,
                  expected_state_rows BIGINT,
                  unique_cache_state_rows BIGINT,
                  duplicate_key_count BIGINT,
                  leakage_violation_count BIGINT,
                  missing_metadata_count BIGINT,
                  evidence_json TEXT,
                  blocking_reasons_json TEXT,
                  created_at TIMESTAMP,
                  updated_at TIMESTAMP
                );
                """
            )
            for column_sql in [
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS cache_key TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS causal_cache_id TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS resolved_run_id TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS model_run_id TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS causal_evidence_id TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS linkage_status TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS linkage_confidence DOUBLE",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS linkage_method TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS feature_scope_id TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS universe_id TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS scope_type TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS feature_version TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS n_states INTEGER",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS cache_start_date DATE",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS cache_end_date DATE",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS model_train_start DATE",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS model_train_end DATE",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS coverage_ratio DOUBLE",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS expected_state_rows BIGINT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS unique_cache_state_rows BIGINT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS duplicate_key_count BIGINT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS leakage_violation_count BIGINT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS missing_metadata_count BIGINT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS evidence_json TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS blocking_reasons_json TEXT",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS created_at TIMESTAMP",
                "ALTER TABLE causal_cache_run_linkage ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
            ]:
                con.execute(column_sql)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS data_health (
                  interface VARCHAR PRIMARY KEY,
                  last_success TIMESTAMP,
                  last_failure TIMESTAMP,
                  last_network_success TIMESTAMP,
                  last_network_failure TIMESTAMP,
                  last_cache_hit TIMESTAMP,
                  last_stale_cache_hit TIMESTAMP,
                  last_error VARCHAR,
                  cache_hits INTEGER DEFAULT 0,
                  network_hits INTEGER DEFAULT 0,
                  stale_reads INTEGER DEFAULT 0
                );
                """
            )
            for column_sql in [
                "ALTER TABLE data_health ADD COLUMN IF NOT EXISTS last_network_success TIMESTAMP",
                "ALTER TABLE data_health ADD COLUMN IF NOT EXISTS last_network_failure TIMESTAMP",
                "ALTER TABLE data_health ADD COLUMN IF NOT EXISTS last_cache_hit TIMESTAMP",
                "ALTER TABLE data_health ADD COLUMN IF NOT EXISTS last_stale_cache_hit TIMESTAMP",
            ]:
                con.execute(column_sql)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS fetch_failures (
                  target_type VARCHAR,
                  board_type VARCHAR,
                  target_name VARCHAR,
                  interface VARCHAR,
                  last_failure TIMESTAMP,
                  last_error VARCHAR,
                  PRIMARY KEY (target_type, board_type, target_name, interface)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS user_universe (
                  universe_id TEXT PRIMARY KEY,
                  universe_name TEXT NOT NULL,
                  description TEXT,
                  created_at TIMESTAMP,
                  updated_at TIMESTAMP,
                  is_default BOOLEAN DEFAULT FALSE
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS user_universe_items (
                  universe_id TEXT,
                  item_type TEXT,
                  item_id TEXT,
                  item_name TEXT,
                  weight DOUBLE DEFAULT 1.0,
                  note TEXT,
                  created_at TIMESTAMP,
                  PRIMARY KEY (universe_id, item_id)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_stock_basket (
                  basket_id TEXT PRIMARY KEY,
                  basket_name TEXT NOT NULL,
                  description TEXT,
                  index_method TEXT DEFAULT 'equal_weight',
                  created_at TIMESTAMP,
                  updated_at TIMESTAMP
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_stock_basket_members (
                  basket_id TEXT,
                  stock_code TEXT,
                  stock_name TEXT,
                  weight DOUBLE DEFAULT 1.0,
                  note TEXT,
                  created_at TIMESTAMP,
                  PRIMARY KEY (basket_id, stock_code)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_basket_ohlcv (
                  basket_id TEXT,
                  trade_date DATE,
                  close DOUBLE,
                  daily_ret DOUBLE,
                  volume DOUBLE,
                  amount DOUBLE,
                  member_count INTEGER,
                  created_at TIMESTAMP,
                  PRIMARY KEY (basket_id, trade_date)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_model_runs (
                  run_id TEXT PRIMARY KEY,
                  model_family TEXT NOT NULL,
                  model_version TEXT NOT NULL,
                  created_at TIMESTAMP NOT NULL,
                  universe_id TEXT,
                  include_custom_baskets BOOLEAN DEFAULT TRUE,
                  feature_scope_id TEXT,
                  feature_version TEXT,
                  start_date DATE,
                  end_date DATE,
                  train_window_days INTEGER,
                  rebalance_days INTEGER,
                  train_frequency TEXT,
                  train_every_n_trade_days INTEGER,
                  snapshot_frequency TEXT,
                  n_states INTEGER,
                  max_duration INTEGER,
                  duration_smoothing DOUBLE,
                  emission_type TEXT,
                  feature_columns_json TEXT,
                  config_json TEXT,
                  config_hash TEXT,
                  run_hash TEXT,
                  clean_run BOOLEAN DEFAULT TRUE,
                  params_json TEXT,
                  params_hash TEXT,
                  code_version TEXT,
                  notes TEXT
                );
                """
            )
            for column_sql in [
                "ALTER TABLE hsmm_model_runs ADD COLUMN IF NOT EXISTS include_custom_baskets BOOLEAN DEFAULT TRUE",
                "ALTER TABLE hsmm_model_runs ADD COLUMN IF NOT EXISTS train_frequency TEXT",
                "ALTER TABLE hsmm_model_runs ADD COLUMN IF NOT EXISTS train_every_n_trade_days INTEGER",
                "ALTER TABLE hsmm_model_runs ADD COLUMN IF NOT EXISTS snapshot_frequency TEXT",
                "ALTER TABLE hsmm_model_runs ADD COLUMN IF NOT EXISTS config_json TEXT",
                "ALTER TABLE hsmm_model_runs ADD COLUMN IF NOT EXISTS config_hash TEXT",
                "ALTER TABLE hsmm_model_runs ADD COLUMN IF NOT EXISTS run_hash TEXT",
                "ALTER TABLE hsmm_model_runs ADD COLUMN IF NOT EXISTS clean_run BOOLEAN DEFAULT TRUE",
            ]:
                con.execute(column_sql)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_model_checkpoints (
                  run_id TEXT,
                  checkpoint_id TEXT,
                  train_date DATE,
                  train_start_date DATE,
                  train_end_date DATE,
                  train_trade_day_count INTEGER,
                  n_sequences INTEGER,
                  n_observations INTEGER,
                  model_version TEXT,
                  feature_columns_json TEXT,
                  state_label_profile_json TEXT,
                  params_json TEXT,
                  params_hash TEXT,
                  config_hash TEXT,
                  created_at TIMESTAMP,
                  PRIMARY KEY (run_id, checkpoint_id)
                );
                """
            )
            con.execute("ALTER TABLE hsmm_model_checkpoints ADD COLUMN IF NOT EXISTS params_hash TEXT")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_run_performance (
                  run_id TEXT,
                  checkpoint_id TEXT,
                  train_date DATE,
                  train_start_date DATE,
                  train_end_date DATE,
                  training_sequence_count INTEGER,
                  training_row_count INTEGER,
                  fit_seconds DOUBLE,
                  decode_snapshot_count INTEGER,
                  decode_sector_count INTEGER,
                  decode_rows_generated INTEGER,
                  decode_seconds DOUBLE,
                  created_at TIMESTAMP,
                  PRIMARY KEY (run_id, checkpoint_id)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_state_daily (
                  run_id TEXT NOT NULL,
                  checkpoint_id TEXT,
                  trade_date DATE NOT NULL,
                  sector_code TEXT NOT NULL,
                  sector_name TEXT,
                  state_id INTEGER NOT NULL,
                  state_label TEXT NOT NULL,
                  state_probability DOUBLE,
                  state_phase TEXT,
                  state_age_days INTEGER,
                  state_age_days_by_id INTEGER,
                  state_age_days_by_label INTEGER,
                  model_state_age_days INTEGER,
                  label_state_age_days INTEGER,
                  duration_model_age_days INTEGER,
                  display_state_age_days INTEGER,
                  duration_percentile DOUBLE,
                  expected_remaining_days DOUBLE,
                  p_stay_1d DOUBLE,
                  p_stay_3d DOUBLE,
                  p_stay_5d DOUBLE,
                  p_stay_10d DOUBLE,
                  p_exit_1d DOUBLE,
                  p_exit_3d DOUBLE,
                  p_exit_5d DOUBLE,
                  p_exit_10d DOUBLE,
                  p_exit_20d DOUBLE,
                  raw_p_exit_1d DOUBLE,
                  raw_p_exit_3d DOUBLE,
                  raw_p_exit_5d DOUBLE,
                  raw_p_exit_10d DOUBLE,
                  raw_p_exit_20d DOUBLE,
                  calibrated_p_exit_1d DOUBLE,
                  calibrated_p_exit_3d DOUBLE,
                  calibrated_p_exit_5d DOUBLE,
                  calibrated_p_exit_10d DOUBLE,
                  calibrated_p_exit_20d DOUBLE,
                  most_likely_next_state_id INTEGER,
                  most_likely_next_state_label TEXT,
                  next_state_probability DOUBLE,
                  viterbi_score DOUBLE,
                  confidence DOUBLE,
                  train_start_date DATE,
                  train_end_date DATE,
                  max_observation_date_used DATE NOT NULL,
                  state_source TEXT NOT NULL,
                  feature_scope_id TEXT,
                  decode_mode TEXT,
                  snapshot_frequency TEXT,
                  created_at TIMESTAMP NOT NULL,
                  PRIMARY KEY (run_id, trade_date, sector_code)
                );
                """
            )
            for column_sql in [
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS checkpoint_id TEXT",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS state_probability DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS state_age_days_by_id INTEGER",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS state_age_days_by_label INTEGER",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS model_state_age_days INTEGER",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS label_state_age_days INTEGER",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS duration_model_age_days INTEGER",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS display_state_age_days INTEGER",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS p_exit_20d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS raw_p_exit_1d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS raw_p_exit_3d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS raw_p_exit_5d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS raw_p_exit_10d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS raw_p_exit_20d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS calibrated_p_exit_1d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS calibrated_p_exit_3d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS calibrated_p_exit_5d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS calibrated_p_exit_10d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS calibrated_p_exit_20d DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS viterbi_score DOUBLE",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS decode_mode TEXT",
                "ALTER TABLE hsmm_state_daily ADD COLUMN IF NOT EXISTS snapshot_frequency TEXT",
            ]:
                con.execute(column_sql)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_state_episodes (
                  run_id TEXT NOT NULL,
                  sector_code TEXT NOT NULL,
                  sector_name TEXT,
                  state_id INTEGER NOT NULL,
                  state_label TEXT NOT NULL,
                  episode_id TEXT,
                  start_date DATE NOT NULL,
                  end_date DATE NOT NULL,
                  duration_days INTEGER NOT NULL,
                  duration_trading_days INTEGER,
                  duration_calendar_days INTEGER,
                  entry_trade_date DATE,
                  exit_trade_date DATE,
                  next_state_id INTEGER,
                  next_state_label TEXT,
                  is_left_censored BOOLEAN DEFAULT FALSE,
                  left_censor_reason TEXT,
                  is_right_censored BOOLEAN DEFAULT FALSE,
                  right_censor_reason TEXT,
                  checkpoint_id_start TEXT,
                  checkpoint_id_end TEXT,
                  is_open_episode BOOLEAN DEFAULT FALSE,
                  created_at TIMESTAMP NOT NULL
                );
                """
            )
            for column_sql in [
                "ALTER TABLE hsmm_state_episodes ADD COLUMN IF NOT EXISTS episode_id TEXT",
                "ALTER TABLE hsmm_state_episodes ADD COLUMN IF NOT EXISTS duration_trading_days INTEGER",
                "ALTER TABLE hsmm_state_episodes ADD COLUMN IF NOT EXISTS duration_calendar_days INTEGER",
                "ALTER TABLE hsmm_state_episodes ADD COLUMN IF NOT EXISTS is_left_censored BOOLEAN DEFAULT FALSE",
                "ALTER TABLE hsmm_state_episodes ADD COLUMN IF NOT EXISTS left_censor_reason TEXT",
                "ALTER TABLE hsmm_state_episodes ADD COLUMN IF NOT EXISTS right_censor_reason TEXT",
                "ALTER TABLE hsmm_state_episodes ADD COLUMN IF NOT EXISTS checkpoint_id_start TEXT",
                "ALTER TABLE hsmm_state_episodes ADD COLUMN IF NOT EXISTS checkpoint_id_end TEXT",
                "ALTER TABLE hsmm_state_episodes ADD COLUMN IF NOT EXISTS is_open_episode BOOLEAN DEFAULT FALSE",
            ]:
                con.execute(column_sql)
            con.execute("UPDATE hsmm_state_episodes SET is_left_censored = TRUE WHERE left_censor_reason IS NOT NULL")
            con.execute("UPDATE hsmm_state_episodes SET is_right_censored = TRUE WHERE right_censor_reason IS NOT NULL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_display_label_episodes (
                  run_id TEXT NOT NULL,
                  sector_code TEXT NOT NULL,
                  sector_name TEXT,
                  state_label TEXT NOT NULL,
                  episode_id TEXT NOT NULL,
                  start_date DATE NOT NULL,
                  end_date DATE NOT NULL,
                  episode_start_date DATE,
                  episode_end_date DATE,
                  start_trade_idx INTEGER,
                  end_trade_idx INTEGER,
                  duration_days INTEGER NOT NULL,
                  duration_trading_days INTEGER,
                  is_open_episode BOOLEAN DEFAULT FALSE,
                  is_left_censored BOOLEAN DEFAULT FALSE,
                  left_censor_reason TEXT,
                  is_right_censored BOOLEAN DEFAULT FALSE,
                  right_censor_reason TEXT,
                  prev_state_label TEXT,
                  previous_state_label TEXT,
                  next_state_label TEXT,
                  created_at TIMESTAMP NOT NULL,
                  PRIMARY KEY (run_id, sector_code, episode_id)
                );
                """
            )
            for column_sql in [
                "ALTER TABLE hsmm_display_label_episodes ADD COLUMN IF NOT EXISTS sector_name TEXT",
                "ALTER TABLE hsmm_display_label_episodes ADD COLUMN IF NOT EXISTS episode_start_date DATE",
                "ALTER TABLE hsmm_display_label_episodes ADD COLUMN IF NOT EXISTS episode_end_date DATE",
                "ALTER TABLE hsmm_display_label_episodes ADD COLUMN IF NOT EXISTS duration_trading_days INTEGER",
                "ALTER TABLE hsmm_display_label_episodes ADD COLUMN IF NOT EXISTS is_open_episode BOOLEAN DEFAULT FALSE",
                "ALTER TABLE hsmm_display_label_episodes ADD COLUMN IF NOT EXISTS previous_state_label TEXT",
            ]:
                con.execute(column_sql)
            con.execute("UPDATE hsmm_display_label_episodes SET episode_start_date = start_date WHERE episode_start_date IS NULL")
            con.execute("UPDATE hsmm_display_label_episodes SET episode_end_date = end_date WHERE episode_end_date IS NULL")
            con.execute("UPDATE hsmm_display_label_episodes SET duration_trading_days = duration_days WHERE duration_trading_days IS NULL")
            con.execute("UPDATE hsmm_display_label_episodes SET previous_state_label = prev_state_label WHERE previous_state_label IS NULL")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_lifecycle_ui_daily (
                  run_id TEXT NOT NULL,
                  profile_mode TEXT NOT NULL DEFAULT 'retrospective',
                  state_date_policy TEXT NOT NULL DEFAULT 'full_run',
                  trade_date DATE NOT NULL,
                  sector_code TEXT NOT NULL,
                  sector_name TEXT,
                  state_label TEXT NOT NULL,
                  display_episode_id TEXT,
                  display_state_age_days INTEGER,
                  display_age_bucket TEXT,
                  display_episode_start_date DATE,
                  state_phase TEXT,
                  historical_median_duration_days DOUBLE,
                  historical_p10_duration_days DOUBLE,
                  historical_p25_duration_days DOUBLE,
                  historical_p33_duration_days DOUBLE,
                  historical_p66_duration_days DOUBLE,
                  historical_p75_duration_days DOUBLE,
                  historical_p90_duration_days DOUBLE,
                  duration_percentile_display DOUBLE,
                  exit_tendency_1d TEXT,
                  exit_tendency_3d TEXT,
                  exit_tendency_5d TEXT,
                  exit_tendency_10d TEXT,
                  exit_tendency_20d TEXT,
                  exit_tendency_score_1d DOUBLE,
                  exit_tendency_score_3d DOUBLE,
                  exit_tendency_score_5d DOUBLE,
                  exit_tendency_score_10d DOUBLE,
                  exit_tendency_score_20d DOUBLE,
                  exit_tendency_basis_1d TEXT,
                  exit_tendency_basis_3d TEXT,
                  exit_tendency_basis_5d TEXT,
                  exit_tendency_basis_10d TEXT,
                  exit_tendency_basis_20d TEXT,
                  probability_display_policy TEXT,
                  probability_status_1d TEXT,
                  probability_status_3d TEXT,
                  probability_status_5d TEXT,
                  probability_status_10d TEXT,
                  probability_status_20d TEXT,
                  raw_score_used_1d BOOLEAN DEFAULT FALSE,
                  raw_score_used_3d BOOLEAN DEFAULT FALSE,
                  raw_score_used_5d BOOLEAN DEFAULT FALSE,
                  raw_score_used_10d BOOLEAN DEFAULT FALSE,
                  raw_score_used_20d BOOLEAN DEFAULT FALSE,
                  next_state_tendency TEXT,
                  next_state_tendency_label TEXT,
                  next_state_tendency_label_status TEXT,
                  next_state_tendency_label_sample_count INTEGER,
                  next_state_tendency_label_top_share DOUBLE,
                  next_state_tendency_phase_aware TEXT,
                  next_state_tendency_phase_status TEXT,
                  next_state_tendency_phase_sample_count INTEGER,
                  next_state_tendency_phase_top_share DOUBLE,
                  next_state_tendency_age_bucket TEXT,
                  next_state_tendency_age_status TEXT,
                  next_state_tendency_age_sample_count INTEGER,
                  next_state_tendency_age_top_share DOUBLE,
                  next_state_tendency_confidence DOUBLE,
                  next_state_tendency_sample_count INTEGER,
                  profile_cutoff_date DATE,
                  profile_sample_window_start DATE,
                  profile_sample_window_end DATE,
                  source_checkpoint_id TEXT,
                  source_run_id TEXT,
                  source_probability_run_id TEXT,
                  state_source TEXT,
                  created_at TIMESTAMP NOT NULL,
                  PRIMARY KEY (run_id, profile_mode, profile_cutoff_date, state_date_policy, trade_date, sector_code)
                );
                """
            )
            for column_sql in [
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS profile_mode TEXT DEFAULT 'retrospective'",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS state_date_policy TEXT DEFAULT 'full_run'",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS display_episode_id TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS display_age_bucket TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS historical_p10_duration_days DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS historical_p25_duration_days DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS historical_p75_duration_days DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_score_1d DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_score_3d DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_score_5d DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_score_10d DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_score_20d DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_basis_1d TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_basis_3d TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_basis_5d TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_basis_10d TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS exit_tendency_basis_20d TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS raw_score_used_1d BOOLEAN DEFAULT FALSE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS raw_score_used_3d BOOLEAN DEFAULT FALSE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS raw_score_used_5d BOOLEAN DEFAULT FALSE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS raw_score_used_10d BOOLEAN DEFAULT FALSE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS raw_score_used_20d BOOLEAN DEFAULT FALSE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_label TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_label_status TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_label_sample_count INTEGER",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_label_top_share DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_phase_aware TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_phase_status TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_phase_sample_count INTEGER",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_phase_top_share DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_age_bucket TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_age_status TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_age_sample_count INTEGER",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_age_top_share DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_confidence DOUBLE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS next_state_tendency_sample_count INTEGER",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS profile_cutoff_date DATE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS profile_sample_window_start DATE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS profile_sample_window_end DATE",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS source_run_id TEXT",
                "ALTER TABLE hsmm_lifecycle_ui_daily ADD COLUMN IF NOT EXISTS source_probability_run_id TEXT",
            ]:
                con.execute(column_sql)
            con.execute("UPDATE hsmm_lifecycle_ui_daily SET profile_mode = 'retrospective' WHERE profile_mode IS NULL")
            con.execute("UPDATE hsmm_lifecycle_ui_daily SET state_date_policy = 'full_run' WHERE state_date_policy IS NULL")
            con.execute("UPDATE hsmm_lifecycle_ui_daily SET profile_cutoff_date = trade_date WHERE profile_cutoff_date IS NULL")
            constraints = con.execute(
                """
                SELECT constraint_text
                FROM duckdb_constraints()
                WHERE table_name = 'hsmm_lifecycle_ui_daily'
                  AND constraint_type = 'PRIMARY KEY'
                """
            ).fetchdf()
            constraint_text = " ".join(constraints["constraint_text"].astype(str).tolist()) if not constraints.empty else ""
            if constraints.empty or "profile_cutoff_date" not in constraint_text or "state_date_policy" not in constraint_text:
                con.execute("DROP TABLE IF EXISTS hsmm_lifecycle_ui_daily_profile_migration")
                con.execute(
                    """
                    CREATE TABLE hsmm_lifecycle_ui_daily_profile_migration AS
                    SELECT * FROM hsmm_lifecycle_ui_daily
                    """
                )
                con.execute("DROP TABLE hsmm_lifecycle_ui_daily")
                con.execute(
                    """
                    CREATE TABLE hsmm_lifecycle_ui_daily (
	                      run_id TEXT NOT NULL,
	                      profile_mode TEXT NOT NULL DEFAULT 'retrospective',
	                      state_date_policy TEXT NOT NULL DEFAULT 'full_run',
	                      trade_date DATE NOT NULL,
                      sector_code TEXT NOT NULL,
                      sector_name TEXT,
                      state_label TEXT NOT NULL,
                      display_episode_id TEXT,
                      display_state_age_days INTEGER,
                      display_age_bucket TEXT,
                      display_episode_start_date DATE,
                      state_phase TEXT,
	                      historical_median_duration_days DOUBLE,
	                      historical_p10_duration_days DOUBLE,
	                      historical_p25_duration_days DOUBLE,
	                      historical_p33_duration_days DOUBLE,
	                      historical_p66_duration_days DOUBLE,
	                      historical_p75_duration_days DOUBLE,
	                      historical_p90_duration_days DOUBLE,
                      duration_percentile_display DOUBLE,
                      exit_tendency_1d TEXT,
                      exit_tendency_3d TEXT,
                      exit_tendency_5d TEXT,
                      exit_tendency_10d TEXT,
                      exit_tendency_20d TEXT,
                      exit_tendency_score_1d DOUBLE,
                      exit_tendency_score_3d DOUBLE,
                      exit_tendency_score_5d DOUBLE,
                      exit_tendency_score_10d DOUBLE,
                      exit_tendency_score_20d DOUBLE,
                      exit_tendency_basis_1d TEXT,
                      exit_tendency_basis_3d TEXT,
                      exit_tendency_basis_5d TEXT,
                      exit_tendency_basis_10d TEXT,
                      exit_tendency_basis_20d TEXT,
                      probability_display_policy TEXT,
                      probability_status_1d TEXT,
                      probability_status_3d TEXT,
                      probability_status_5d TEXT,
                      probability_status_10d TEXT,
                      probability_status_20d TEXT,
                      raw_score_used_1d BOOLEAN DEFAULT FALSE,
                      raw_score_used_3d BOOLEAN DEFAULT FALSE,
                      raw_score_used_5d BOOLEAN DEFAULT FALSE,
	                      raw_score_used_10d BOOLEAN DEFAULT FALSE,
	                      raw_score_used_20d BOOLEAN DEFAULT FALSE,
	                      next_state_tendency TEXT,
	                      next_state_tendency_label TEXT,
	                      next_state_tendency_label_status TEXT,
	                      next_state_tendency_label_sample_count INTEGER,
	                      next_state_tendency_label_top_share DOUBLE,
	                      next_state_tendency_phase_aware TEXT,
	                      next_state_tendency_phase_status TEXT,
	                      next_state_tendency_phase_sample_count INTEGER,
	                      next_state_tendency_phase_top_share DOUBLE,
	                      next_state_tendency_age_bucket TEXT,
	                      next_state_tendency_age_status TEXT,
	                      next_state_tendency_age_sample_count INTEGER,
	                      next_state_tendency_age_top_share DOUBLE,
	                      next_state_tendency_confidence DOUBLE,
                      next_state_tendency_sample_count INTEGER,
                      profile_cutoff_date DATE,
                      profile_sample_window_start DATE,
                      profile_sample_window_end DATE,
                      source_checkpoint_id TEXT,
                      source_run_id TEXT,
	                      source_probability_run_id TEXT,
	                      state_source TEXT,
	                      created_at TIMESTAMP NOT NULL,
	                      PRIMARY KEY (run_id, profile_mode, profile_cutoff_date, state_date_policy, trade_date, sector_code)
	                    )
                    """
                )
                lifecycle_cols = [
                    "run_id", "profile_mode", "state_date_policy", "trade_date", "sector_code", "sector_name", "state_label",
                    "display_episode_id", "display_state_age_days", "display_age_bucket", "display_episode_start_date",
                    "state_phase", "historical_median_duration_days", "historical_p10_duration_days",
                    "historical_p25_duration_days", "historical_p33_duration_days", "historical_p66_duration_days",
                    "historical_p75_duration_days", "historical_p90_duration_days",
                    "duration_percentile_display", "exit_tendency_1d", "exit_tendency_3d", "exit_tendency_5d",
                    "exit_tendency_10d", "exit_tendency_20d", "exit_tendency_score_1d", "exit_tendency_score_3d",
                    "exit_tendency_score_5d", "exit_tendency_score_10d", "exit_tendency_score_20d",
                    "exit_tendency_basis_1d", "exit_tendency_basis_3d", "exit_tendency_basis_5d",
                    "exit_tendency_basis_10d", "exit_tendency_basis_20d", "probability_display_policy",
                    "probability_status_1d", "probability_status_3d", "probability_status_5d",
                    "probability_status_10d", "probability_status_20d", "raw_score_used_1d", "raw_score_used_3d",
                    "raw_score_used_5d", "raw_score_used_10d", "raw_score_used_20d", "next_state_tendency",
                    "next_state_tendency_label", "next_state_tendency_label_status",
                    "next_state_tendency_label_sample_count", "next_state_tendency_label_top_share",
                    "next_state_tendency_phase_aware", "next_state_tendency_phase_status",
                    "next_state_tendency_phase_sample_count", "next_state_tendency_phase_top_share",
                    "next_state_tendency_age_bucket", "next_state_tendency_age_status",
                    "next_state_tendency_age_sample_count", "next_state_tendency_age_top_share",
                    "next_state_tendency_confidence", "next_state_tendency_sample_count", "profile_cutoff_date",
                    "profile_sample_window_start", "profile_sample_window_end", "source_checkpoint_id",
                    "source_run_id", "source_probability_run_id", "state_source", "created_at",
                ]
                con.execute(
                    f"""
                    INSERT INTO hsmm_lifecycle_ui_daily ({", ".join(lifecycle_cols)})
                    SELECT {", ".join(lifecycle_cols)}
                    FROM hsmm_lifecycle_ui_daily_profile_migration
                    """
                )
                con.execute("DROP TABLE hsmm_lifecycle_ui_daily_profile_migration")
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_lifecycle_profile_metadata (
                  run_id TEXT NOT NULL,
	                  profile_run_id TEXT NOT NULL,
	                  profile_mode TEXT,
	                  profile_cutoff_date DATE,
	                  state_date_policy TEXT,
	                  source_probability_report_path TEXT,
	                  source_probability_run_id TEXT,
	                  horizons TEXT,
	                  state_labels TEXT,
	                  completed_episode_count INTEGER,
	                  profile_window_start DATE,
	                  profile_window_end DATE,
	                  state_row_count INTEGER,
	                  state_window_start DATE,
	                  state_window_end DATE,
	                  created_at TIMESTAMP,
	                  notes TEXT,
	                  PRIMARY KEY (run_id, profile_run_id)
	                );
	                """
	            )
            for column_sql in [
                "ALTER TABLE hsmm_lifecycle_profile_metadata ADD COLUMN IF NOT EXISTS state_date_policy TEXT",
                "ALTER TABLE hsmm_lifecycle_profile_metadata ADD COLUMN IF NOT EXISTS state_row_count INTEGER",
                "ALTER TABLE hsmm_lifecycle_profile_metadata ADD COLUMN IF NOT EXISTS state_window_start DATE",
                "ALTER TABLE hsmm_lifecycle_profile_metadata ADD COLUMN IF NOT EXISTS state_window_end DATE",
            ]:
                con.execute(column_sql)
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_lifecycle_duration_profile (
                  run_id TEXT NOT NULL,
                  profile_mode TEXT NOT NULL,
                  profile_cutoff_date DATE NOT NULL,
                  state_label TEXT NOT NULL,
                  completed_episode_count INTEGER,
                  mean_duration_days DOUBLE,
                  median_duration_days DOUBLE,
                  p10_duration_days DOUBLE,
                  p25_duration_days DOUBLE,
                  p75_duration_days DOUBLE,
                  p90_duration_days DOUBLE,
                  left_censored_count INTEGER,
                  right_censored_count INTEGER,
                  profile_sample_window_start DATE,
                  profile_sample_window_end DATE,
                  created_at TIMESTAMP,
                  PRIMARY KEY (run_id, profile_mode, profile_cutoff_date, state_label)
                );
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_next_state_tendency_profile (
                  run_id TEXT NOT NULL,
                  profile_mode TEXT NOT NULL,
                  profile_cutoff_date DATE,
                  state_label TEXT NOT NULL,
                  state_phase TEXT NOT NULL DEFAULT '__ALL__',
                  age_bucket TEXT NOT NULL DEFAULT '__ALL__',
                  sample_count INTEGER,
                  top_next_state_label TEXT,
                  top_next_state_share DOUBLE,
                  next_state_distribution_json TEXT,
                  next_state_tendency TEXT,
	                  confidence DOUBLE,
	                  status TEXT,
	                  created_at TIMESTAMP,
	                  PRIMARY KEY (run_id, profile_mode, profile_cutoff_date, state_label, state_phase, age_bucket)
	                );
	                """
	            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS hsmm_parameters (
                  run_id TEXT PRIMARY KEY,
                  state_labels_json TEXT,
                  startprob_json TEXT,
                  transition_matrix_json TEXT,
                  duration_pmf_json TEXT,
                  emission_mean_json TEXT,
                  emission_var_json TEXT,
                  scaler_json TEXT,
                  created_at TIMESTAMP NOT NULL
                );
                """
            )
            next_constraints = con.execute(
                """
                SELECT constraint_text
                FROM duckdb_constraints()
                WHERE table_name = 'hsmm_next_state_tendency_profile'
                  AND constraint_type = 'PRIMARY KEY'
                """
            ).fetchdf()
            next_constraint_text = " ".join(next_constraints["constraint_text"].astype(str).tolist()) if not next_constraints.empty else ""
            if next_constraints.empty or "profile_cutoff_date" not in next_constraint_text:
                con.execute("DROP TABLE IF EXISTS hsmm_next_state_tendency_profile_migration")
                con.execute(
                    """
                    CREATE TABLE hsmm_next_state_tendency_profile_migration AS
                    SELECT * FROM hsmm_next_state_tendency_profile
                    """
                )
                con.execute("DROP TABLE hsmm_next_state_tendency_profile")
                con.execute(
                    """
                    CREATE TABLE hsmm_next_state_tendency_profile (
                      run_id TEXT NOT NULL,
                      profile_mode TEXT NOT NULL,
                      profile_cutoff_date DATE NOT NULL,
                      state_label TEXT NOT NULL,
                      state_phase TEXT NOT NULL DEFAULT '__ALL__',
                      age_bucket TEXT NOT NULL DEFAULT '__ALL__',
                      sample_count INTEGER,
                      top_next_state_label TEXT,
                      top_next_state_share DOUBLE,
                      next_state_distribution_json TEXT,
                      next_state_tendency TEXT,
                      confidence DOUBLE,
                      status TEXT,
                      created_at TIMESTAMP,
                      PRIMARY KEY (run_id, profile_mode, profile_cutoff_date, state_label, state_phase, age_bucket)
                    )
                    """
                )
                con.execute(
                    """
                    INSERT INTO hsmm_next_state_tendency_profile (
                      run_id, profile_mode, profile_cutoff_date, state_label, state_phase, age_bucket,
                      sample_count, top_next_state_label, top_next_state_share, next_state_distribution_json,
                      next_state_tendency, confidence, status, created_at
                    )
                    SELECT run_id, profile_mode, COALESCE(profile_cutoff_date, DATE '1970-01-01'),
                           state_label, state_phase, age_bucket, sample_count, top_next_state_label,
                           top_next_state_share, next_state_distribution_json, next_state_tendency,
                           confidence, status, created_at
                    FROM hsmm_next_state_tendency_profile_migration
                    """
                )
                con.execute("DROP TABLE hsmm_next_state_tendency_profile_migration")
            from src.evaluation.evidence_registry import ensure_evidence_registry_schema_for_connection

            ensure_evidence_registry_schema_for_connection(con)

    def upsert_df(self, table: str, df: pd.DataFrame, key_cols: Iterable[str]) -> None:
        if df.empty:
            return
        cols = list(df.columns)
        key_cols = list(key_cols)
        updates = [c for c in cols if c not in key_cols]
        update_sql = ", ".join([f"{c}=excluded.{c}" for c in updates])
        col_sql = ", ".join(cols)
        with _DB_WRITE_LOCK, self.connect() as con:
            con.register("incoming", df)
            if update_sql:
                con.execute(
                    f"""
                    INSERT INTO {table} ({col_sql})
                    SELECT {col_sql} FROM incoming
                    ON CONFLICT ({", ".join(key_cols)}) DO UPDATE SET {update_sql}
                    """
                )
            else:
                con.execute(
                    f"""
                    INSERT INTO {table} ({col_sql})
                    SELECT {col_sql} FROM incoming
                    ON CONFLICT ({", ".join(key_cols)}) DO NOTHING
                    """
                )

    def read_df(self, sql: str, params: tuple | list | None = None) -> pd.DataFrame:
        with self.connect() as con:
            return con.execute(sql, params or []).fetchdf()

    def latest_run_id(self, universe_id: str | None = None, scope_type: str | None = None) -> str | None:
        where: list[str] = []
        params: list[object] = []
        if scope_type:
            where.append("scope_type = ?")
            params.append(scope_type)
        if universe_id is not None:
            where.append("universe_id = ?")
            params.append(universe_id)
        sql = "SELECT run_id FROM model_runs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT 1"
        df = self.read_df(sql, params)
        return None if df.empty else str(df.loc[0, "run_id"])

    def latest_run_for_current_scope(self, universe_id: str | None = None) -> str | None:
        if universe_id:
            return self.latest_run_id(universe_id=universe_id, scope_type="universe")
        return self.latest_run_id(scope_type="all")

    def get_model_run(self, run_id: str | None) -> pd.DataFrame:
        if not run_id:
            return pd.DataFrame()
        return self.read_df(
            """
            SELECT run_id, model_type, n_states, train_start, train_end, feature_version,
                   universe_id, scope_type, include_custom_baskets,
                   feature_scope_id, feature_scope_type, created_at, metrics_json
            FROM model_runs
            WHERE run_id = ?
            """,
            [run_id],
        )

    def update_health_success(self, interface: str, cache_hit: bool = False, stale: bool = False) -> None:
        with _DB_WRITE_LOCK, self.connect() as con:
            if cache_hit:
                if stale:
                    con.execute(
                        """
                        INSERT INTO data_health(interface, last_cache_hit, last_stale_cache_hit, cache_hits, stale_reads)
                        VALUES (?, now(), now(), ?, ?)
                        ON CONFLICT(interface) DO UPDATE SET
                          last_cache_hit=excluded.last_cache_hit,
                          last_stale_cache_hit=excluded.last_stale_cache_hit,
                          cache_hits=data_health.cache_hits + excluded.cache_hits,
                          stale_reads=data_health.stale_reads + excluded.stale_reads
                        """,
                        [interface, 1, 1],
                    )
                else:
                    con.execute(
                        """
                        INSERT INTO data_health(interface, last_cache_hit, cache_hits, stale_reads)
                        VALUES (?, now(), ?, ?)
                        ON CONFLICT(interface) DO UPDATE SET
                          last_cache_hit=excluded.last_cache_hit,
                          cache_hits=data_health.cache_hits + excluded.cache_hits,
                          stale_reads=data_health.stale_reads + excluded.stale_reads
                        """,
                        [interface, 1, 0],
                    )
            else:
                con.execute(
                    """
                    INSERT INTO data_health(interface, last_success, last_network_success, last_error, network_hits)
                    VALUES (?, now(), now(), NULL, ?)
                    ON CONFLICT(interface) DO UPDATE SET
                      last_success=excluded.last_success,
                      last_network_success=excluded.last_network_success,
                      last_error=NULL,
                      network_hits=data_health.network_hits + excluded.network_hits
                    """,
                    [interface, 1],
                )

    def update_health_failure(self, interface: str, error: Exception | str) -> None:
        with _DB_WRITE_LOCK, self.connect() as con:
            con.execute(
                """
                INSERT INTO data_health(interface, last_failure, last_network_failure, last_error)
                VALUES (?, now(), now(), ?)
                ON CONFLICT(interface) DO UPDATE SET
                  last_failure=excluded.last_failure,
                  last_network_failure=excluded.last_network_failure,
                  last_error=excluded.last_error
                """,
                [interface, str(error)[:1000]],
            )

    def record_fetch_failure(self, target_type: str, board_type: str, target_name: str, interface: str, error: Exception | str) -> None:
        with _DB_WRITE_LOCK, self.connect() as con:
            con.execute(
                """
                INSERT INTO fetch_failures(target_type, board_type, target_name, interface, last_failure, last_error)
                VALUES (?, ?, ?, ?, now(), ?)
                ON CONFLICT(target_type, board_type, target_name, interface) DO UPDATE SET
                  last_failure=excluded.last_failure,
                  last_error=excluded.last_error
                """,
                [target_type, board_type, target_name, interface, str(error)[:1000]],
            )

    def clear_fetch_failure(self, target_type: str, board_type: str, target_name: str, interface: str | None = None) -> None:
        with _DB_WRITE_LOCK, self.connect() as con:
            if interface is None:
                con.execute(
                    "DELETE FROM fetch_failures WHERE target_type = ? AND board_type = ? AND target_name = ?",
                    [target_type, board_type, target_name],
                )
            else:
                con.execute(
                    "DELETE FROM fetch_failures WHERE target_type = ? AND board_type = ? AND target_name = ? AND interface = ?",
                    [target_type, board_type, target_name, interface],
                )

    @staticmethod
    def _id(prefix: str, name: str) -> str:
        safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name).strip())
        safe = "_".join(part for part in safe.split("_") if part)[:40] or prefix
        return f"{prefix}:{safe}_{uuid.uuid4().hex[:8]}"

    def create_universe(self, name: str, description: str = "") -> str:
        universe_id = self._id("universe", name)
        df = pd.DataFrame([{"universe_id": universe_id, "universe_name": name, "description": description, "created_at": pd.Timestamp.now(), "updated_at": pd.Timestamp.now(), "is_default": False}])
        self.upsert_df("user_universe", df, ["universe_id"])
        return universe_id

    def list_universes(self) -> pd.DataFrame:
        return self.read_df("SELECT * FROM user_universe ORDER BY is_default DESC, updated_at DESC, universe_name")

    def get_universe(self, universe_id: str) -> pd.DataFrame:
        return self.read_df("SELECT * FROM user_universe WHERE universe_id = ?", [universe_id])

    def set_default_universe(self, universe_id: str) -> None:
        with _DB_WRITE_LOCK, self.connect() as con:
            con.execute("UPDATE user_universe SET is_default = FALSE")
            con.execute("UPDATE user_universe SET is_default = TRUE, updated_at = now() WHERE universe_id = ?", [universe_id])

    def delete_universe(self, universe_id: str) -> None:
        with _DB_WRITE_LOCK, self.connect() as con:
            con.execute("DELETE FROM user_universe_items WHERE universe_id = ?", [universe_id])
            con.execute("DELETE FROM user_universe WHERE universe_id = ?", [universe_id])

    def add_universe_item(self, universe_id: str, item_type: str, item_id: str, item_name: str, weight: float = 1.0, note: str = "") -> None:
        df = pd.DataFrame([{"universe_id": universe_id, "item_type": item_type, "item_id": item_id, "item_name": item_name, "weight": float(weight), "note": note, "created_at": pd.Timestamp.now()}])
        self.upsert_df("user_universe_items", df, ["universe_id", "item_id"])
        with _DB_WRITE_LOCK, self.connect() as con:
            con.execute("UPDATE user_universe SET updated_at = now() WHERE universe_id = ?", [universe_id])

    def remove_universe_item(self, universe_id: str, item_id: str) -> None:
        with _DB_WRITE_LOCK, self.connect() as con:
            con.execute("DELETE FROM user_universe_items WHERE universe_id = ? AND item_id = ?", [universe_id, item_id])
            con.execute("UPDATE user_universe SET updated_at = now() WHERE universe_id = ?", [universe_id])

    def list_universe_items(self, universe_id: str) -> pd.DataFrame:
        return self.read_df("SELECT * FROM user_universe_items WHERE universe_id = ? ORDER BY item_type, item_name", [universe_id])

    def create_custom_stock_basket(self, name: str, description: str = "", index_method: str = "equal_weight") -> str:
        basket_id = self._id("custom", name)
        df = pd.DataFrame([{"basket_id": basket_id, "basket_name": name, "description": description, "index_method": index_method, "created_at": pd.Timestamp.now(), "updated_at": pd.Timestamp.now()}])
        self.upsert_df("custom_stock_basket", df, ["basket_id"])
        return basket_id

    def add_basket_members(self, basket_id: str, members: list[dict[str, object]] | pd.DataFrame) -> None:
        df = pd.DataFrame(members).copy()
        if df.empty:
            return
        df["basket_id"] = basket_id
        df["stock_code"] = df["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(df["stock_code"].astype(str)).str.zfill(6)
        if "stock_name" not in df.columns:
            df["stock_name"] = ""
        if "weight" not in df.columns:
            df["weight"] = 1.0
        if "note" not in df.columns:
            df["note"] = ""
        df["created_at"] = pd.Timestamp.now()
        self.upsert_df("custom_stock_basket_members", df[["basket_id", "stock_code", "stock_name", "weight", "note", "created_at"]], ["basket_id", "stock_code"])
        with _DB_WRITE_LOCK, self.connect() as con:
            con.execute("UPDATE custom_stock_basket SET updated_at = now() WHERE basket_id = ?", [basket_id])

    def remove_basket_member(self, basket_id: str, stock_code: str) -> None:
        with _DB_WRITE_LOCK, self.connect() as con:
            con.execute("DELETE FROM custom_stock_basket_members WHERE basket_id = ? AND stock_code = ?", [basket_id, str(stock_code).zfill(6)])
            con.execute("UPDATE custom_stock_basket SET updated_at = now() WHERE basket_id = ?", [basket_id])

    def list_basket_members(self, basket_id: str) -> pd.DataFrame:
        return self.read_df("SELECT * FROM custom_stock_basket_members WHERE basket_id = ? ORDER BY stock_code", [basket_id])

    def upsert_custom_basket_ohlcv(self, df: pd.DataFrame) -> None:
        self.upsert_df("custom_basket_ohlcv", df, ["basket_id", "trade_date"])

    def export_universe_json(self, universe_id: str) -> dict[str, object]:
        universe = self.get_universe(universe_id)
        items = self.list_universe_items(universe_id)
        baskets: list[dict[str, object]] = []
        for item in items[items["item_type"] == "custom_stock_basket"].itertuples(index=False):
            basket = self.read_df("SELECT * FROM custom_stock_basket WHERE basket_id = ?", [item.item_id])
            if basket.empty:
                continue
            baskets.append({"basket": basket.iloc[0].to_dict(), "members": self.list_basket_members(item.item_id).to_dict(orient="records")})
        return {"universe": universe.iloc[0].to_dict() if not universe.empty else {}, "items": items.to_dict(orient="records"), "baskets": baskets}

    def import_universe_json(self, payload: dict[str, object]) -> str:
        universe = dict(payload.get("universe", {}) or {})
        universe_id = str(universe.get("universe_id") or self._id("universe", universe.get("universe_name", "imported")))
        now = pd.Timestamp.now()
        df = pd.DataFrame([{"universe_id": universe_id, "universe_name": universe.get("universe_name", "导入板块池"), "description": universe.get("description", ""), "created_at": universe.get("created_at", now), "updated_at": now, "is_default": bool(universe.get("is_default", False))}])
        self.upsert_df("user_universe", df, ["universe_id"])
        for item in payload.get("items", []) or []:
            row = dict(item)
            self.add_universe_item(universe_id, str(row["item_type"]), str(row["item_id"]), str(row.get("item_name", row["item_id"])), float(row.get("weight", 1.0)), str(row.get("note", "")))
        for entry in payload.get("baskets", []) or []:
            basket = dict(entry.get("basket", {}))
            if basket:
                self.upsert_df("custom_stock_basket", pd.DataFrame([basket]), ["basket_id"])
                self.add_basket_members(str(basket["basket_id"]), entry.get("members", []))
        return universe_id


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
