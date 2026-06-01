from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

import src.data_sources.akshare_client as ak_client
import src.data_sources.ths_helpers as ths_helpers
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.akshare_client import AKShareClient
from src.data_sources.ths_helpers import ths_board_code, ths_board_constituents, ths_board_hist, ths_board_names


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _html(codes: list[str], page_info: str = "1/1") -> str:
    rows = "".join(f"<tr><td>{code}</td><td>股票{code[-1]}</td></tr>" for code in codes)
    return f"""
    <html>
      <body>
        <span class="page_info">{page_info}</span>
        <table>
          <thead><tr><th>代码</th><th>名称</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </body>
    </html>
    """


def test_ths_board_names_and_hist_use_single_helper_surface():
    fake_ak = SimpleNamespace(
        stock_board_industry_name_ths=lambda: pd.DataFrame({"name": ["半导体"], "code": ["881121"]}),
        stock_board_concept_name_ths=lambda: pd.DataFrame({"name": ["CPO概念"], "code": ["885001"]}),
        stock_board_industry_index_ths=lambda symbol, start_date, end_date: pd.DataFrame(
            {"symbol": [symbol], "start": [start_date], "end": [end_date]}
        ),
        stock_board_concept_index_ths=lambda symbol, start_date, end_date: pd.DataFrame(
            {"symbol": [symbol], "start": [start_date], "end": [end_date]}
        ),
    )

    assert ths_board_names(fake_ak, "industry").loc[0, "name"] == "半导体"
    assert ths_board_code(fake_ak, "concept", "CPO概念") == "885001"
    hist = ths_board_hist(fake_ak, "industry", "半导体", "20240101", "20240131")

    assert hist.loc[0, "symbol"] == "半导体"
    assert hist.loc[0, "start"] == "20240101"


def test_ths_board_constituents_parses_all_pages(monkeypatch):
    fake_ak = SimpleNamespace(stock_board_industry_name_ths=lambda: pd.DataFrame({"name": ["半导体"], "code": ["881121"]}))
    monkeypatch.setattr(ths_helpers, "ths_cookie_header", lambda board_type: {"Cookie": "v=test"})
    calls: list[str] = []

    def fake_get(url: str, headers: dict[str, str], timeout: int) -> FakeResponse:
        calls.append(url)
        if "page/1" in url:
            return FakeResponse(_html(["000001"], page_info="1/2"))
        return FakeResponse(_html(["000002"], page_info="2/2"))

    out = ths_board_constituents(fake_ak, "industry", "半导体", request_get=fake_get)

    assert out["代码"].astype(str).tolist() == ["000001", "000002"]
    assert len(calls) == 2


def test_akshare_client_constituents_fallback_uses_shared_helpers(monkeypatch, tmp_path):
    fake_ak = SimpleNamespace()
    monkeypatch.setattr(ak_client, "_import_akshare", lambda: fake_ak)
    monkeypatch.setattr(ak_client, "ths_board_constituents", lambda ak, board_type, sector_name: (_ for _ in ()).throw(RuntimeError("ths down")))
    monkeypatch.setattr(
        ak_client,
        "em_board_constituents",
        lambda ak, board_type, sector_name: pd.DataFrame({"代码": ["000001"], "名称": ["平安银行"]}),
    )
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    client = AKShareClient(cache_dir=tmp_path / "cache", storage=storage, use_subprocess_for_ths=False)
    monkeypatch.setattr(client, "_sleep", lambda: None)

    res = client.board_constituents("industry", "银行")

    assert res.data.loc[0, "sector_id"] == "industry:银行"
    assert res.data.loc[0, "stock_code"] == "000001"
