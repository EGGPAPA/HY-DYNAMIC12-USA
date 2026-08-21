import json
from pathlib import Path

import pandas as pd
import streamlit as st

from engine import analyze
from leader import leader_metrics
from kis_us import yf_daily, yf_price

TOP12_FILE = Path("data/usa_top12.json")
ETF_TOP12_FILE = Path("data/usa_etf_top12.json")

ETF_UNIVERSE = {
    "SPY": "SPDR S&P 500 ETF Trust",
    "QQQ": "Invesco QQQ Trust",
    "VOO": "Vanguard S&P 500 ETF",
    "IWM": "iShares Russell 2000 ETF",
    "DIA": "SPDR Dow Jones Industrial Average ETF",
    "XLK": "Technology Select Sector SPDR Fund",
    "SMH": "VanEck Semiconductor ETF",
    "SOXX": "iShares Semiconductor ETF",
    "XLF": "Financial Select Sector SPDR Fund",
    "XLE": "Energy Select Sector SPDR Fund",
    "XLV": "Health Care Select Sector SPDR Fund",
    "XLI": "Industrial Select Sector SPDR Fund",
    "XLY": "Consumer Discretionary Select Sector SPDR Fund",
    "XLP": "Consumer Staples Select Sector SPDR Fund",
    "XLU": "Utilities Select Sector SPDR Fund",
    "XLB": "Materials Select Sector SPDR Fund",
    "VNQ": "Vanguard Real Estate ETF",
    "TLT": "iShares 20+ Year Treasury Bond ETF",
    "IEF": "iShares 7-10 Year Treasury Bond ETF",
    "GLD": "SPDR Gold Shares",
    "SLV": "iShares Silver Trust",
    "GDX": "VanEck Gold Miners ETF",
    "ARKK": "ARK Innovation ETF",
    "IGV": "iShares Expanded Tech-Software Sector ETF",
    "XBI": "SPDR S&P Biotech ETF",
}


def _load(path):
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, list) else []
    except Exception:
        pass
    return []


def _save(path, rows):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _judge(score):
    if score >= 82:
        return "🟢 적극매수"
    if score >= 74:
        return "🟡 매수후보"
    if score >= 64:
        return "🔵 관찰"
    return "⚪ 현금대기"


def _price_table(rows, asset_type):
    if not rows:
        st.info(f"저장된 {asset_type} 분석 결과가 없습니다.")
        return
    view = []
    for i, r in enumerate(rows[:12], 1):
        p = float(r.get("현재가($)", 0) or 0)
        e1 = float(r.get("1차매수가($)", 0) or 0)
        e2 = float(r.get("2차매수가($)", 0) or 0)
        stop = float(r.get("3%손절가($)", 0) or (e1 * .97 if e1 else 0))
        score = float(r.get("판정점수", r.get("USA점수", 0)) or 0)
        view.append({
            "순위": i,
            "구분": asset_type,
            "종목": r.get("종목", r.get("name", "")),
            "티커": r.get("티커", r.get("ticker", "")),
            "현재가($)": p,
            "점수": score,
            "판정": r.get("판정", _judge(score)),
            "1차매수가($)": e1,
            "2차매수가($)": e2,
            "손절(-3%)": stop,
            "+15%": (e1 * 1.15 if e1 else 0),
            "+20%": (e1 * 1.20 if e1 else 0),
            "+25%": (e1 * 1.25 if e1 else 0),
        })
    df = pd.DataFrame(view)
    money_cols = ["현재가($)", "1차매수가($)", "2차매수가($)", "손절(-3%)", "+15%", "+20%", "+25%"]
    for c in money_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "점수": st.column_config.ProgressColumn("점수", min_value=0, max_value=100, format="%.1f"),
            **{c: st.column_config.NumberColumn(c, format="$%.2f") for c in money_cols},
        },
    )


def render_stock_tab():
    st.subheader("🇺🇸 미국 개별종목 TOP12")
    st.caption("기존 HY DYNAMIC12 USA 정밀분석 결과에서 ETF를 제외한 개별기업만 표시합니다.")
    rows = _load(TOP12_FILE)
    stocks = [r for r in rows if str(r.get("티커", "")).upper() not in ETF_UNIVERSE]
    c1, c2, c3 = st.columns(3)
    c1.metric("개별종목", min(12, len(stocks)))
    c2.metric("적극매수", sum(str(r.get("판정", "")).startswith("적극매수") for r in stocks[:12]))
    c3.metric("ETF 제외", "적용")
    _price_table(stocks, "개별종목")
    st.info("개별종목 스캔은 기존 ‘미국시장 스캔 → 정밀분석’ 결과를 사용하며 ETF는 이 화면에서 자동 제외합니다.")


def _scan_etfs():
    rows = []
    bar = st.progress(0)
    status = st.empty()
    items = list(ETF_UNIVERSE.items())
    for i, (sym, name) in enumerate(items):
        status.info(f"ETF 분석 {i+1}/{len(items)} · {sym}")
        try:
            d = yf_daily(sym)
            a = analyze(d)
            lm = leader_metrics(d)
            px = float(yf_price(sym, d))
            score = round(lm["leader_score"] * .55 + a["score"] * .35 + min(100, a["value_ratio"] * 50) * .10, 1)
            if lm.get("near_high", 0) >= 98 and a.get("gap", 0) > 6:
                score = min(score, 73.9)
            signal = _judge(score)
            entry1 = float(a.get("entry", px) or px)
            entry2 = float(a.get("entry2", entry1 * .95) or entry1 * .95)
            rows.append({
                "순위": 0,
                "종목": name,
                "티커": sym,
                "현재가($)": round(px, 2),
                "USA점수": score,
                "판정점수": score,
                "판정": signal,
                "1차매수가($)": round(entry1, 2),
                "2차매수가($)": round(entry2, 2),
                "3%손절가($)": round(entry1 * .97, 2),
                "주도주": round(float(lm.get("leader_score", 0)), 1),
                "기술": round(float(a.get("score", 0)), 1),
            })
        except Exception as e:
            st.caption(f"{sym} 분석 제외: {type(e).__name__}")
        bar.progress((i + 1) / len(items))
    rows.sort(key=lambda x: x.get("USA점수", 0), reverse=True)
    rows = rows[:12]
    for i, r in enumerate(rows, 1):
        r["순위"] = i
    _save(ETF_TOP12_FILE, rows)
    bar.empty()
    status.success(f"ETF TOP12 계산 완료 · {len(rows)}개")
    return rows


def render_etf_tab():
    st.subheader("📊 미국 ETF TOP12")
    st.caption("ETF는 기업 재무점수를 쓰지 않고 추세·상대강도·거래강도로 별도 평가합니다.")
    rows = _load(ETF_TOP12_FILE)
    c1, c2, c3 = st.columns(3)
    c1.metric("ETF 유니버스", len(ETF_UNIVERSE))
    c2.metric("저장 TOP12", len(rows[:12]))
    c3.metric("운용", "개별종목과 분리")
    if st.button("🔄 ETF TOP12 다시 계산", type="primary", use_container_width=True, key="hy_usa_etf_scan"):
        rows = _scan_etfs()
    _price_table(rows, "ETF")
    st.info("ETF의 -3% / +15% / +20% / +25% 기준은 1차매수가를 기준으로 계산합니다. 기업 PER·ROE 등 재무점수는 ETF 판정에 사용하지 않습니다.")
