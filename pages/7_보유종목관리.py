import base64
import json
import os
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

REPO = "EGGPAPA/HY-DYNAMIC12-USA"
BRANCH = "main"
HOLDINGS_PATH = "holdings.json"
GITHUB_API = f"https://api.github.com/repos/{REPO}/contents/{HOLDINGS_PATH}"
GITHUB_PAT = os.getenv("GITHUB_PAT", "").strip()

st.set_page_config(page_title="보유종목 관리", page_icon="💼", layout="wide")
@st.fragment(run_every="10s")
def render_live_holdings_page():
    st.title("💼 보유종목 관리")
    st.caption("실제 체결 매수가와 수량을 직접 입력하면 평균매수가를 자동 계산해 holdings.json에 저장합니다.")
    
    
    def _headers():
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if GITHUB_PAT:
            h["Authorization"] = f"Bearer {GITHUB_PAT}"
        return h
    
    
    def load_holdings():
        r = requests.get(GITHUB_API, headers=_headers(), params={"ref": BRANCH}, timeout=20)
        if r.status_code == 404:
            return [], None
        if r.status_code != 200:
            raise RuntimeError(f"holdings.json 읽기 실패: HTTP {r.status_code} / {r.text[:300]}")
        data = r.json()
        raw = base64.b64decode(data["content"]).decode("utf-8")
        rows = json.loads(raw or "[]")
        if not isinstance(rows, list):
            raise ValueError("holdings.json은 JSON 배열이어야 합니다.")
        return rows, data.get("sha")
    
    
    def save_holdings(rows, sha, message):
        if not GITHUB_PAT:
            raise RuntimeError("Streamlit Secrets에 GITHUB_PAT가 필요합니다.")
        content = json.dumps(rows, ensure_ascii=False, indent=2)
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": BRANCH,
        }
        if sha:
            payload["sha"] = sha
        r = requests.put(GITHUB_API, headers=_headers(), json=payload, timeout=20)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"holdings.json 저장 실패: HTTP {r.status_code} / {r.text[:300]}")
        return True
    
    
    def find_holding(rows, ticker):
        t = ticker.strip().upper()
        for i, row in enumerate(rows):
            if str(row.get("ticker", "")).strip().upper() == t and str(row.get("status", "holding")).lower() != "closed":
                return i, row
        return None, None
    
    
    @st.cache_data(ttl=10, show_spinner=False)
    def current_prices(tickers):
        symbols=[str(x).strip().upper() for x in tickers if str(x).strip()]
        if not symbols:
            return {}
        prices={}
        for period, interval in (("1d","1m"),("5d","1d")):
            missing=[x for x in symbols if x not in prices]
            if not missing:
                break
            try:
                data=yf.download(missing,period=period,interval=interval,prepost=False,
                                 auto_adjust=True,progress=False,threads=True,group_by="ticker")
                for ticker in missing:
                    try:
                        d=data[ticker] if isinstance(data.columns,pd.MultiIndex) else data
                        close=pd.to_numeric(d["Close"],errors="coerce").dropna()
                        if not close.empty:
                            prices[ticker]=float(close.iloc[-1])
                    except Exception:
                        continue
            except Exception:
                continue
        return prices
    
    
    try:
        holdings, holdings_sha = load_holdings()
    except Exception as e:
        st.error(str(e))
        holdings, holdings_sha = [], None
    
    active = [x for x in holdings if str(x.get("status", "holding")).lower() != "closed" and x.get("enabled", True)]
    
    c1, c2, c3 = st.columns(3)
    c1.metric("보유 종목", len(active))
    c2.metric("GitHub 저장", "가능" if GITHUB_PAT else "GITHUB_PAT 필요")
    c3.metric("자동감시", "연결됨")
    
    if active:
        prices=current_prices(tuple(str(r.get("ticker","")).strip().upper() for r in active))
        view = []
        for r in active:
            avg = float(r.get("average_price", 0) or 0)
            qty = float(r.get("quantity", 0) or 0)
            ticker = str(r.get("ticker", "")).strip().upper()
            current = prices.get(ticker)
            return_pct = ((current / avg) - 1) * 100 if current is not None and avg > 0 else None
            view.append({
                "티커": ticker,
                "종목명": r.get("name", ""),
                "평균매수가($)": round(avg, 4),
                "현재가($)": round(current, 2) if current is not None else "조회 대기",
                "수익률(%)": round(return_pct, 2) if return_pct is not None else None,
                "수량": qty,
                "투입금액($)": round(avg * qty, 2),
                "손절(-3%)": round(avg * 0.97, 2) if avg else None,
                "+15%": round(avg * 1.15, 2) if avg else None,
                "+20%": round(avg * 1.20, 2) if avg else None,
                "+25%": round(avg * 1.25, 2) if avg else None,
            })
        table = pd.DataFrame(view)
    
        def return_color(value):
            if pd.isna(value):
                return "color: #a0a8b8; font-weight: 700"
            if float(value) > 0:
                return "color: #ff4b4b; font-weight: 800"
            if float(value) < 0:
                return "color: #4da3ff; font-weight: 800"
            return "color: #f0f2f6; font-weight: 700"
    
        styled = (
            table.style
            .format(
                {
                    "평균매수가($)": lambda value: f"{float(value):,.2f}",
                    "현재가($)": lambda value: value if isinstance(value, str) else f"{float(value):,.2f}",
                    "수익률(%)": lambda value: f"{float(value):+.2f}",
                    "수량": lambda value: f"{float(value):g}",
                    "투입금액($)": lambda value: f"{float(value):,.2f}",
                    "손절(-3%)": lambda value: f"{float(value):,.2f}",
                    "+15%": lambda value: f"{float(value):,.2f}",
                    "+20%": lambda value: f"{float(value):,.2f}",
                    "+25%": lambda value: f"{float(value):,.2f}",
                },
                na_rep="-",
                escape="html",
            )
            .map(return_color, subset=["수익률(%)"])
            .set_properties(**{"font-size": "16px", "padding": "10px 12px"})
            .set_table_styles([
                {"selector": "table", "props": [("width", "100%"), ("border-collapse", "collapse")]},
                {"selector": "th", "props": [("font-size", "16px"), ("font-weight", "800"), ("padding", "11px 12px"), ("text-align", "left")]},
                {"selector": "td", "props": [("font-size", "16px"), ("font-weight", "600"), ("white-space", "nowrap")]},
            ])
            .hide(axis="index")
        )
        st.markdown(
            f'<div style="width:100%;overflow-x:auto">{styled.to_html()}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("현재 등록된 보유종목이 없습니다.")
    
    st.divider()
    st.subheader("매수 등록 / 추가 매수")
    
    with st.form("buy_form", clear_on_submit=False):
        a, b = st.columns(2)
        ticker = a.text_input("티커", placeholder="예: NU").strip().upper()
        name = b.text_input("종목명", placeholder="예: Nu Holdings")
        c, d = st.columns(2)
        buy_price = c.number_input("실제 체결 매수가($)", min_value=0.0, step=0.01, format="%.4f")
        buy_qty = d.number_input("매수 수량", min_value=0.0, step=1.0, format="%.4f")
        submitted = st.form_submit_button("➕ 보유 등록 / 추가 매수", type="primary", use_container_width=True)
    
    if submitted:
        if not ticker or buy_price <= 0 or buy_qty <= 0:
            st.error("티커, 실제 매수가, 수량을 정확히 입력하세요.")
        else:
            try:
                holdings, holdings_sha = load_holdings()
                idx, old = find_holding(holdings, ticker)
                now = datetime.now(timezone.utc).isoformat()
    
                if old is None:
                    new_row = {
                        "ticker": ticker,
                        "name": name or ticker,
                        "mode": "holding",
                        "status": "holding",
                        "average_price": round(float(buy_price), 6),
                        "quantity": round(float(buy_qty), 6),
                        "stop_loss_pct": 3,
                        "enabled": True,
                        "updated_at": now,
                    }
                    holdings.append(new_row)
                    msg = f"Add holding {ticker}"
                    new_avg = float(buy_price)
                    new_qty = float(buy_qty)
                else:
                    old_avg = float(old.get("average_price", 0) or 0)
                    old_qty = float(old.get("quantity", 0) or 0)
                    new_qty = old_qty + float(buy_qty)
                    new_avg = ((old_avg * old_qty) + (float(buy_price) * float(buy_qty))) / new_qty
                    old.update({
                        "ticker": ticker,
                        "name": name or old.get("name") or ticker,
                        "mode": "holding",
                        "status": "holding",
                        "average_price": round(new_avg, 6),
                        "quantity": round(new_qty, 6),
                        "stop_loss_pct": float(old.get("stop_loss_pct", 3) or 3),
                        "enabled": True,
                        "updated_at": now,
                    })
                    holdings[idx] = old
                    msg = f"Update holding {ticker}"
    
                save_holdings(holdings, holdings_sha, msg)
                st.success(f"{ticker} 저장 완료 · 평균매수가 ${new_avg:.4f} · 총수량 {new_qty:g}")
                st.rerun()
            except Exception as e:
                st.error(str(e))
    
    st.divider()
    st.subheader("전량 매도 처리")
    
    active_tickers = [str(x.get("ticker", "")).strip().upper() for x in active if x.get("ticker")]
    if active_tickers:
        sell_ticker = st.selectbox("전량 매도할 종목", active_tickers)
        if st.button("✅ 전량 매도 → 감시 종료", use_container_width=True):
            try:
                holdings, holdings_sha = load_holdings()
                idx, old = find_holding(holdings, sell_ticker)
                if old is None:
                    st.warning("해당 보유종목을 찾지 못했습니다.")
                else:
                    old["status"] = "closed"
                    old["enabled"] = False
                    old["closed_at"] = datetime.now(timezone.utc).isoformat()
                    holdings[idx] = old
                    save_holdings(holdings, holdings_sha, f"Close holding {sell_ticker}")
                    st.success(f"{sell_ticker} 전량 매도 처리 완료 · 자동감시 종료")
                    st.rerun()
            except Exception as e:
                st.error(str(e))
    else:
        st.caption("전량 매도 처리할 보유종목이 없습니다.")
    
    st.info("보유종목은 TOP12에서 빠져도 holdings.json에 남아 있으며, GitHub Actions가 미국 정규장 동안 평균매수가 기준 -3%, +15%, +20%, +25%를 계속 감시합니다.")
    
    

render_live_holdings_page()
