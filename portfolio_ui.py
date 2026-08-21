import json
from pathlib import Path

import pandas as pd
import streamlit as st

TOP12_FILE = Path("data/usa_top12.json")
ETF_TOP12_FILE = Path("data/usa_etf_top12.json")

INDEX_ETFS = {"SPY", "VOO", "QQQ", "IWM", "DIA"}
SECTOR_ETFS = {"XLK", "SMH", "SOXX", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "VNQ", "IGV", "XBI", "GDX", "ARKK"}


def _load(path):
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _score(row):
    try:
        return float(row.get("판정점수", row.get("USA점수", 0)) or 0)
    except Exception:
        return 0.0


def _ticker(row):
    return str(row.get("티커", row.get("ticker", ""))).strip().upper()


def _name(row):
    return str(row.get("종목", row.get("name", _ticker(row))))


def _pick(rows, allowed=None, n=3):
    picked = []
    for r in sorted(rows, key=_score, reverse=True):
        t = _ticker(r)
        if not t or (allowed is not None and t not in allowed):
            continue
        picked.append(r)
        if len(picked) >= n:
            break
    return picked


def _allocation_rows(capital, etfs, stocks):
    index = _pick(etfs, INDEX_ETFS, 2)
    sector = _pick(etfs, SECTOR_ETFS, 3)
    individual = _pick(stocks, None, 4)

    result = []
    groups = [
        ("지수 ETF", 40.0, index),
        ("섹터 ETF", 30.0, sector),
        ("개별종목", 20.0, individual),
    ]
    for group, pct, picks in groups:
        if picks:
            each_pct = pct / len(picks)
            for r in picks:
                result.append({
                    "구분": group,
                    "종목": _name(r),
                    "티커": _ticker(r),
                    "목표비중(%)": round(each_pct, 1),
                    "배정금액($)": round(capital * each_pct / 100, 2),
                    "점수": round(_score(r), 1),
                    "판정": r.get("판정", ""),
                })
        else:
            result.append({"구분": group, "종목": "분석 결과 생성 필요", "티커": "-", "목표비중(%)": pct,
                           "배정금액($)": round(capital * pct / 100, 2), "점수": 0, "판정": "대기"})
    result.append({"구분": "현금", "종목": "USD 현금", "티커": "CASH", "목표비중(%)": 10.0,
                   "배정금액($)": round(capital * .10, 2), "점수": None, "판정": "대기자금"})
    return result


def render_portfolio_tab():
    st.subheader("🧭 미국 포트폴리오 · 40/30/20/10")
    st.caption("지수 ETF 40% · 섹터 ETF 30% · 개별종목 20% · 현금 10%를 기본 원칙으로 운용합니다.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("지수 ETF", "40%")
    c2.metric("섹터 ETF", "30%")
    c3.metric("개별종목", "20%")
    c4.metric("현금", "10%")

    capital = st.number_input("미국주식 운용금액($)", min_value=1000.0, value=10000.0, step=1000.0, format="%.0f", key="hy_usa_portfolio_capital")

    etfs = _load(ETF_TOP12_FILE)
    stocks = _load(TOP12_FILE)
    rows = _allocation_rows(float(capital), etfs, stocks)
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True,
        column_config={
            "목표비중(%)": st.column_config.ProgressColumn("목표비중(%)", min_value=0, max_value=40, format="%.1f%%"),
            "배정금액($)": st.column_config.NumberColumn("배정금액($)", format="$%.2f"),
            "점수": st.column_config.NumberColumn("점수", format="%.1f"),
        })

    st.markdown("#### 운용 규칙")
    st.write("지수 ETF는 포트폴리오의 중심축으로 40%를 유지하고, 섹터 ETF는 현재 강한 업종 중 상위 종목에 30%를 분산합니다. 개별종목은 HY DYNAMIC12 USA 상위 후보에만 총 20%를 배정합니다. 나머지 10%는 조정장·급락장 추가매수용 현금으로 유지합니다.")
    st.info("ETF TOP12와 개별종목 TOP12를 다시 계산하면 이 포트폴리오의 추천 종목도 자동으로 바뀝니다. 비중 40/30/20/10은 고정 기준입니다.")
