import json
from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf

from usa_asset_split_ui import ETF_UNIVERSE

TOP12_FILE = Path("data/usa_top12.json")
CAND_FILE = Path("data/usa_candidates.json")


def _load(path):
    try:
        if path.exists():
            x = json.loads(path.read_text(encoding="utf-8"))
            return x if isinstance(x, list) else []
    except Exception:
        pass
    return []


def _universe(include_etf=True):
    names = {}
    for path in (CAND_FILE, TOP12_FILE):
        for r in _load(path):
            t = str(r.get("symbol") or r.get("티커") or "").strip().upper()
            if t:
                names[t] = str(r.get("name") or r.get("종목") or t)
    if include_etf:
        names.update(ETF_UNIVERSE)
    return names


def _scan_one(ticker, name):
    d = yf.download(ticker, period="2y", interval="1mo", auto_adjust=True,
                    progress=False, threads=False)
    if d is None or d.empty or len(d) < 7:
        return None
    close = d["Close"]
    vol = d["Volume"] if "Volume" in d else None
    if isinstance(close, pd.DataFrame): close = close.iloc[:, 0]
    if isinstance(vol, pd.DataFrame): vol = vol.iloc[:, 0]
    close = pd.to_numeric(close, errors="coerce").dropna()
    if len(close) < 7: return None

    ma5 = close.rolling(5).mean()
    cur, prev = float(close.iloc[-1]), float(close.iloc[-2])
    cur_ma, prev_ma = float(ma5.iloc[-1]), float(ma5.iloc[-2])
    crossed = prev <= prev_ma and cur > cur_ma
    above = cur > cur_ma
    breakout = (cur / cur_ma - 1) * 100 if cur_ma else 0

    prior = close.iloc[-5:-1]
    down_months = int((prior.diff().dropna() < 0).sum())
    correction = (float(prior.max()) / max(cur, 1e-9) - 1) * 100
    ma_turn = cur_ma > prev_ma

    vol_ratio = None
    if vol is not None:
        vv = pd.to_numeric(vol, errors="coerce").dropna()
        if len(vv) >= 6 and float(vv.iloc[-6:-1].mean()) > 0:
            vol_ratio = float(vv.iloc[-1] / vv.iloc[-6:-1].mean())

    strength = 0
    strength += 45 if crossed else (15 if above else 0)
    strength += 20 if ma_turn else 0
    strength += 15 if down_months >= 2 else 0
    strength += 10 if correction >= 5 else 0
    strength += 10 if vol_ratio is not None and vol_ratio >= 1.2 else 0

    if crossed and ma_turn and strength >= 75:
        judge = "🔥 강한 신규돌파"
    elif crossed:
        judge = "🟢 신규돌파"
    elif above and 0 <= breakout <= 5:
        judge = "🟡 돌파근접/유지"
    else:
        judge = "⚪ 제외"

    return {"종목": name, "티커": ticker, "현재가($)": round(cur, 2),
            "5개월선($)": round(cur_ma, 2), "돌파율(%)": round(breakout, 2),
            "최근4개월 하락횟수": down_months, "조정폭(%)": round(correction, 1),
            "5개월선 상승": "예" if ma_turn else "아니오",
            "거래량배수": round(vol_ratio, 2) if vol_ratio is not None else None,
            "돌파점수": strength, "판정": judge, "_crossed": crossed}


def scan_monthly_breakouts(include_etf=True, only_new=False, progress=None, status=None):
    rows=[];items=list(_universe(include_etf).items())
    for i,(ticker,name) in enumerate(items):
        if status is not None:status.caption(f"{i+1}/{len(items)} · {ticker} 월봉 확인")
        try:
            row=_scan_one(ticker,name)
            if row and (not only_new or row["_crossed"]):rows.append(row)
        except Exception:pass
        if progress is not None:progress.progress((i+1)/max(1,len(items)))
    rows.sort(key=lambda x:(x["_crossed"],x["돌파점수"],x["돌파율(%)"]),reverse=True)
    return rows


def render_monthly_breakout_tab():
    st.subheader("🔥 월봉 5개월 이동평균선 돌파")
    st.caption("월봉 5개월선 신규 돌파 + 조정기간 + 이동평균선 방향 + 거래량을 함께 확인합니다. 진행 중인 월봉은 월말 확정 전 신호가 바뀔 수 있습니다.")
    c1, c2 = st.columns(2)
    include_etf = c1.checkbox("ETF 포함", value=True, key="ma5_etf")
    only_new = c2.checkbox("신규 돌파만 표시", value=True, key="ma5_new")

    names = _universe(include_etf)
    st.info(f"현재 스캔 대상 {len(names)}개 · 미국시장 후보/TOP12" + (" + 주요 ETF" if include_etf else ""))
    if st.button("🔎 월봉 5개월선 돌파 스캔", type="primary", use_container_width=True, key="ma5_scan"):
        bar=st.progress(0); status=st.empty()
        rows=scan_monthly_breakouts(include_etf,False,bar,status)
        st.session_state["monthly_ma5_rows"]=rows
        bar.empty(); status.empty()

    rows=st.session_state.get("monthly_ma5_rows",[])
    if rows:
        view=[r.copy() for r in rows if (r["_crossed"] if only_new else r["판정"]!="⚪ 제외")]
        for r in view: r.pop("_crossed",None)
        a,b,c=st.columns(3)
        a.metric("신규 돌파",sum(1 for r in rows if r["_crossed"]))
        b.metric("강한 돌파",sum(1 for r in rows if r["판정"].startswith("🔥")))
        c.metric("5개월선 위",sum(1 for r in rows if r["돌파율(%)"]>0))
        if view:
            st.dataframe(pd.DataFrame(view),use_container_width=True,hide_index=True)
        else:
            st.warning("현재 조건에 맞는 신규 돌파 종목이 없습니다.")
        st.caption("※ 월중 신호는 잠정 신호입니다. 월말 종가가 5개월 이동평균선 위에서 확정되는지 다시 확인하세요.")

