from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from src.features.sector_features import FEATURE_COLUMNS


@dataclass
class FeaturePreprocessor:
    columns: list[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))
    lower_quantile: float = 0.01
    upper_quantile: float = 0.99
    lower_bounds: dict[str, float] = field(default_factory=dict)
    upper_bounds: dict[str, float] = field(default_factory=dict)
    scaler: StandardScaler = field(default_factory=StandardScaler)

    def fit(self, df: pd.DataFrame) -> "FeaturePreprocessor":
        clipped = df.copy()
        self.lower_bounds = {}
        self.upper_bounds = {}
        for col in self.columns:
            values = pd.to_numeric(clipped[col], errors="coerce")
            if values.notna().sum() > 10:
                lo, hi = values.quantile([self.lower_quantile, self.upper_quantile])
            else:
                lo, hi = values.min(), values.max()
            self.lower_bounds[col] = float(lo) if np.isfinite(lo) else float("-inf")
            self.upper_bounds[col] = float(hi) if np.isfinite(hi) else float("inf")
            clipped[col] = values.clip(self.lower_bounds[col], self.upper_bounds[col])
        self.scaler.fit(clipped[self.columns].to_numpy(dtype=float))
        return self

    def transform_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in self.columns:
            values = pd.to_numeric(out[col], errors="coerce")
            out[col] = values.clip(self.lower_bounds.get(col, float("-inf")), self.upper_bounds.get(col, float("inf")))
        return out

    def transform_array(self, df: pd.DataFrame) -> np.ndarray:
        clipped = self.transform_frame(df)
        return self.scaler.transform(clipped[self.columns].to_numpy(dtype=float))

    def fit_transform_array(self, df: pd.DataFrame) -> np.ndarray:
        self.fit(df)
        return self.transform_array(df)
