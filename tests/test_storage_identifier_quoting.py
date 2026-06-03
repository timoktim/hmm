from __future__ import annotations

import pandas as pd
import pytest

from src.data_pipeline.storage import DuckDBStorage


def test_upsert_rejects_illegal_table_name(tmp_path):
    storage = DuckDBStorage(tmp_path / "identifier.duckdb")
    storage.init_schema()
    df = pd.DataFrame([{"sector_id": "S", "sector_type": "industry", "sector_name": "S"}])

    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        storage.upsert_df("sector_meta; DROP TABLE sector_meta", df, ["sector_id"])


def test_upsert_rejects_illegal_column_name(tmp_path):
    storage = DuckDBStorage(tmp_path / "identifier.duckdb")
    storage.init_schema()
    df = pd.DataFrame([{"sector_id": "S", "sector_name); DROP TABLE sector_meta; --": "S"}])

    with pytest.raises(ValueError, match="Unsafe SQL identifier"):
        storage.upsert_df("sector_meta", df, ["sector_id"])


def test_upsert_rejects_missing_key_column(tmp_path):
    storage = DuckDBStorage(tmp_path / "identifier.duckdb")
    storage.init_schema()
    df = pd.DataFrame([{"sector_id": "S", "sector_type": "industry", "sector_name": "S"}])

    with pytest.raises(ValueError, match="upsert key columns missing"):
        storage.upsert_df("sector_meta", df, ["missing_key"])


def test_legal_upsert_still_works(tmp_path):
    storage = DuckDBStorage(tmp_path / "identifier.duckdb")
    storage.init_schema()

    storage.upsert_df(
        "sector_meta",
        pd.DataFrame([{"sector_id": "S", "sector_type": "industry", "sector_name": "Old"}]),
        ["sector_id"],
    )
    storage.upsert_df(
        "sector_meta",
        pd.DataFrame([{"sector_id": "S", "sector_type": "industry", "sector_name": "New"}]),
        ["sector_id"],
    )

    row = storage.read_df("SELECT sector_name FROM sector_meta WHERE sector_id = ?", ["S"]).iloc[0]
    assert row["sector_name"] == "New"
