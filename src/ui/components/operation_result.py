from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

import pandas as pd
import streamlit as st


def _summary_dict(summary: Any) -> dict[str, Any]:
    if summary is None:
        return {}
    if is_dataclass(summary):
        return asdict(summary)
    if isinstance(summary, dict):
        return dict(summary)
    if isinstance(summary, pd.Series):
        return summary.to_dict()
    if hasattr(summary, "__dict__"):
        return dict(summary.__dict__)
    return {"result": summary}


def operation_summary_line(summary: Any) -> str:
    data = _summary_dict(summary)
    failures = data.get("failures", data.get("failure", []))
    if failures is None:
        failure_count = 0
    elif isinstance(failures, list):
        failure_count = len(failures)
    elif isinstance(failures, str):
        failure_count = 1 if failures else 0
    else:
        failure_count = int(bool(failures))
    success = data.get("updated", data.get("sectors_updated", data.get("successes", data.get("rows", 0))))
    cache_hits = data.get("cache_hits", 0)
    stale_reads = data.get("stale_reads", int(bool(data.get("stale", False))))
    rows = data.get("rows", data.get("row_count", "无"))
    skipped = int(data.get("skipped", 0) or 0)
    skipped_text = f"，跳过 {skipped}" if skipped else ""
    return f"成功 {success}，失败 {failure_count}{skipped_text}，缓存命中 {cache_hits}，过期缓存 {stale_reads}，写入行数 {rows}"


def render_operation_result(summary: Any, title: str = "操作完成", expanded: bool = False) -> None:
    data = _summary_dict(summary)
    line = operation_summary_line(summary)
    failures = data.get("failures", data.get("failure", []))
    has_failure = bool(failures)
    if has_failure:
        st.warning(f"{title}：{line}")
    else:
        st.success(f"{title}：{line}")
    with st.expander("查看详细日志", expanded=expanded):
        st.write(data)
