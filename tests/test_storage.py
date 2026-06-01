from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage


def test_duckdb_upsert_deduplicates(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    df = pd.DataFrame(
        [
            {
                "sector_id": "industry:a",
                "sector_type": "industry",
                "sector_name": "a",
                "source": "test",
                "last_update": pd.Timestamp("2024-01-01"),
            },
            {
                "sector_id": "industry:a",
                "sector_type": "industry",
                "sector_name": "a2",
                "source": "test",
                "last_update": pd.Timestamp("2024-01-02"),
            },
        ]
    )
    storage.upsert_df("sector_meta", df.iloc[[0]], ["sector_id"])
    storage.upsert_df("sector_meta", df.iloc[[1]], ["sector_id"])
    out = storage.read_df("SELECT * FROM sector_meta")
    assert len(out) == 1
    assert out.loc[0, "sector_name"] == "a2"

