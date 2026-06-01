from __future__ import annotations

import importlib
from io import StringIO
from typing import Literal

import pandas as pd
import requests
from bs4 import BeautifulSoup


BoardType = Literal["industry", "concept"]


def ths_board_names(ak: object, board_type: BoardType) -> pd.DataFrame:
    if board_type == "industry":
        return ak.stock_board_industry_name_ths()
    return ak.stock_board_concept_name_ths()


def ths_board_hist(ak: object, board_type: BoardType, sector_name: str, start_date: str, end_date: str) -> pd.DataFrame:
    if board_type == "industry":
        return ak.stock_board_industry_index_ths(symbol=sector_name, start_date=start_date, end_date=end_date)
    return ak.stock_board_concept_index_ths(symbol=sector_name, start_date=start_date, end_date=end_date)


def ths_cookie_header(board_type: BoardType) -> dict[str, str]:
    import py_mini_racer

    module_name = "akshare.stock_feature.stock_board_industry_ths" if board_type == "industry" else "akshare.stock_feature.stock_board_concept_ths"
    module = importlib.import_module(module_name)
    js_code = py_mini_racer.MiniRacer()
    js_code.eval(module._get_file_content_ths("ths.js"))
    return {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://q.10jqka.com.cn",
        "Cookie": f"v={js_code.call('v')}",
    }


def ths_board_code(ak: object, board_type: BoardType, sector_name: str) -> str:
    names = ths_board_names(ak, board_type)
    names = names.rename(columns={"name": "sector_name", "code": "code", "名称": "sector_name", "代码": "code"})
    matched = names[names["sector_name"].astype(str) == str(sector_name)]
    if matched.empty:
        raise ValueError(f"同花顺缺少板块代码: {sector_name}")
    return str(matched.iloc[0]["code"])


def ths_board_constituents(
    ak: object,
    board_type: BoardType,
    sector_name: str,
    request_get: object = requests.get,
) -> pd.DataFrame:
    code = ths_board_code(ak, board_type, sector_name)
    board_path = "thshy" if board_type == "industry" else "gn"
    headers = ths_cookie_header(board_type)
    first_url = f"http://q.10jqka.com.cn/{board_path}/detail/code/{code}/field/199112/order/desc/page/1/ajax/1/"
    first_response = request_get(first_url, headers=headers, timeout=20)
    first_response.raise_for_status()
    soup = BeautifulSoup(first_response.text, features="lxml")
    page_info = soup.find(name="span", attrs={"class": "page_info"})
    page_num = int(page_info.text.split("/")[1]) if page_info and "/" in page_info.text else 1
    frames: list[pd.DataFrame] = []
    for page in range(1, page_num + 1):
        url = f"http://q.10jqka.com.cn/{board_path}/detail/code/{code}/field/199112/order/desc/page/{page}/ajax/1/"
        response = first_response if page == 1 else request_get(url, headers=headers, timeout=20)
        response.raise_for_status()
        try:
            frames.append(pd.read_html(StringIO(response.text))[0])
        except ValueError:
            break
    if not frames:
        raise ValueError(f"同花顺成分股返回空数据: {sector_name}")
    df = pd.concat(frames, ignore_index=True)
    if "代码" not in df.columns or "名称" not in df.columns:
        raise ValueError(f"同花顺成分股缺少代码或名称列: {sector_name}")
    out = df[["代码", "名称"]].copy()
    out["代码"] = out["代码"].astype(str).str.extract(r"(\d{1,6})", expand=False).fillna(out["代码"].astype(str)).str.zfill(6)
    return out.drop_duplicates("代码")


def em_board_constituents(ak: object, board_type: BoardType, sector_name: str) -> pd.DataFrame:
    if board_type == "industry":
        df = ak.stock_board_industry_cons_em(symbol=sector_name)
    else:
        df = ak.stock_board_concept_cons_em(symbol=sector_name)
    if df is None or df.empty:
        raise ValueError(f"东方财富成分股返回空数据: {sector_name}")
    return df
