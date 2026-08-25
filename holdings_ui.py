import base64
import json
import os
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from usa_asset_split_ui import render_stock_tab, render_etf_tab, ETF_UNIVERSE
from portfolio_ui import render_portfolio_tab
from monthly_breakout_ui import render_monthly_breakout_tab

REPO = "EGGPAPA/HY-DYNAMIC12-USA"
BRANCH = "main"
HOLDINGS_PATH = "holdings.json"
API_URL = f"https://api.github.com/repos/{REPO}/contents/{HOLDINGS_PATH}"


def _github_pat():
    try:
        v = st.secrets.get("GITHUB_PAT", "")
        if v:
            return str(v).strip()
    except Exception:
        pass
    return os.getenv("GITHUB_PAT", "").strip()


def _headers():
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if _github_pat(): h["Authorization"] = f"Bearer {_github_pat()}"
    return h


def _load_holdings():
    r = requests.get(API_URL, headers=_headers(), params={"ref": BRANCH}, timeout=20)
    if r.status_code == 404: return [], None
    if r.status_code != 200: raise RuntimeError(f"holdings.json 읽기 실패: HTTP {r.status_code} / {r.text[:250]}")
    data = r.json(); rows = json.loads(base64.b64decode(data["content"]).decode("utf-8") or "[]")
    return (rows if isinstance(rows, list) else []), data.get("sha")


def _save_holdings(rows, sha, message):
    if not _github_pat(): raise RuntimeError("Streamlit Secrets에 GITHUB_PAT를 등록하세요.")
    text = json.dumps(rows, ensure_ascii=False, indent=2)
    payload = {"message": message, "content": base64.b64encode(text.encode()).decode(), "branch": BRANCH}
    if sha: payload["sha"] = sha
    r = requests.put(API_URL, headers=_headers(), json=payload, timeout=20)
    if r.status_code not in (200, 201): raise RuntimeError(f"holdings.json 저장 실패: HTTP {r.status_code} / {r.text[:250]}")


def _find(rows, ticker):
    t = ticker.strip().upper()
    for i, row in enumerate(rows):
        if str(row.get("ticker", "")).strip().upper() == t and str(row.get("status", "holding")).lower() != "closed": return i, row
    return None, None


def _asset_type(row):
    saved = str(row.get("asset_type", "")).strip().upper()
    if saved in {"STOCK", "ETF"}: return saved
    return "ETF" if str(row.get("ticker", "")).strip().upper() in ETF_UNIVERSE else "STOCK"


@st.cache_data(ttl=60, show_spinner=False)
def _current_prices(tickers):
    symbols=[str(x).strip().upper() for x in tickers if str(x).strip()]
    if not symbols:
        return {}
    prices={}
    try:
        data=yf.download(symbols,period="1d",interval="1m",prepost=False,
                         auto_adjust=True,progress=False,threads=True,group_by="ticker")
        for ticker in symbols:
            try:
                d=data[ticker] if isinstance(data.columns,pd.MultiIndex) else data
                close=pd.to_numeric(d["Close"],errors="coerce").dropna()
                if not close.empty:
                    prices[ticker]=float(close.iloc[-1])
            except Exception:
                continue
    except Exception:
        pass
    missing=[x for x in symbols if x not in prices]
    if missing:
        try:
            data=yf.download(missing,period="5d",interval="1d",auto_adjust=True,
                             progress=False,threads=True,group_by="ticker")
            for ticker in missing:
                try:
                    d=data[ticker] if isinstance(data.columns,pd.MultiIndex) else data
                    close=pd.to_numeric(d["Close"],errors="coerce").dropna()
                    if not close.empty:
                        prices[ticker]=float(close.iloc[-1])
                except Exception:
                    continue
        except Exception:
            pass
    return prices


def _holding_table(rows, label):
    if not rows:
        st.info(f"현재 등록된 {label} 보유종목이 없습니다."); return
    prices=_current_prices(tuple(str(r.get("ticker","")).strip().upper() for r in rows))
    view=[]
    for r in rows:
        avg=float(r.get("average_price",0) or 0); qty=float(r.get("quantity",0) or 0)
        ticker=str(r.get("ticker","")).strip().upper(); current=prices.get(ticker)
        return_pct=((current/avg)-1)*100 if current is not None and avg>0 else None
        view.append({"구분":"ETF" if _asset_type(r)=="ETF" else "개별종목","티커":ticker,"종목명":r.get("name",""),
                     "평균매수가($)":round(avg,4),"현재가($)":round(current,2) if current is not None else "조회 대기",
                     "수익률(%)":round(return_pct,2) if return_pct is not None else None,
                     "수량":qty,"투입금액($)":round(avg*qty,2),"손절(-3%)":round(avg*.97,2),
                     "+15%":round(avg*1.15,2),"+20%":round(avg*1.20,2),"+25%":round(avg*1.25,2)})
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


def render_holdings_tab():
    st.subheader("💼 미국 보유종목 관리")
    st.caption("개별종목과 ETF를 구분해 관리하며 추가 매수 시 평균매수가를 자동 계산합니다.")
    try: rows,sha=_load_holdings()
    except Exception as e: st.error(str(e)); rows,sha=[],None
    active=[x for x in rows if str(x.get("status","holding")).lower()!="closed" and x.get("enabled",True)]
    stocks=[x for x in active if _asset_type(x)=="STOCK"]; etfs=[x for x in active if _asset_type(x)=="ETF"]
    c1,c2,c3,c4=st.columns(4); c1.metric("전체 보유",len(active)); c2.metric("개별종목",len(stocks)); c3.metric("ETF",len(etfs)); c4.metric("GitHub 저장","준비됨" if _github_pat() else "PAT 미설정")
    h1,h2=st.tabs(["🇺🇸 개별종목 보유","📊 ETF 보유"])
    with h1: _holding_table(stocks,"개별종목")
    with h2: _holding_table(etfs,"ETF")
    with st.form("hy_holding_buy_form",clear_on_submit=False):
        st.markdown("#### 매수 등록 / 추가 매수"); a0,a,b=st.columns([.8,1,2]); asset_type=a0.selectbox("구분",["개별종목","ETF"],key="hy_hold_asset_type"); ticker=a.text_input("티커",placeholder="예: NVDA / QQQ",key="hy_hold_ticker").strip().upper(); name=b.text_input("종목명",key="hy_hold_name").strip(); c,d=st.columns(2); price=c.number_input("실제 체결 매수가($)",min_value=0.0,step=.01,format="%.4f",key="hy_hold_price"); qty=d.number_input("매수 수량",min_value=0.0,step=1.0,format="%.4f",key="hy_hold_qty"); submitted=st.form_submit_button("➕ 보유 등록 / 추가 매수",type="primary",use_container_width=True)
    if submitted:
        if not ticker or price<=0 or qty<=0: st.error("티커, 실제 체결 매수가, 수량을 입력하세요.")
        else:
            try:
                rows,sha=_load_holdings(); idx,old=_find(rows,ticker); now=datetime.now(timezone.utc).isoformat(); kind="ETF" if asset_type=="ETF" else "STOCK"
                if old is None:
                    new_avg,new_qty=float(price),float(qty); rows.append({"ticker":ticker,"name":name or ticker,"asset_type":kind,"mode":"holding","status":"holding","average_price":round(new_avg,6),"quantity":round(new_qty,6),"stop_loss_pct":3,"enabled":True,"updated_at":now})
                else:
                    old_avg,old_qty=float(old.get("average_price",0) or 0),float(old.get("quantity",0) or 0); new_qty=old_qty+float(qty); new_avg=((old_avg*old_qty)+float(price)*float(qty))/new_qty; old.update({"name":name or old.get("name") or ticker,"asset_type":kind,"average_price":round(new_avg,6),"quantity":round(new_qty,6),"status":"holding","enabled":True,"updated_at":now}); rows[idx]=old
                _save_holdings(rows,sha,f"Update {kind} holding {ticker}"); st.success(f"{ticker} 저장 완료 · 평균매수가 ${new_avg:,.4f} · 총수량 {new_qty:g}"); st.rerun()
            except Exception as e: st.error(str(e))
    st.markdown("#### 전량 매도 처리"); tickers=[str(x.get("ticker","")).strip().upper() for x in active if x.get("ticker")]
    if tickers:
        sell=st.selectbox("전량 매도할 종목",tickers,key="hy_hold_close_ticker")
        if st.button("✅ 전량 매도 → 감시 종료",use_container_width=True,key="hy_hold_close_btn"):
            try:
                rows,sha=_load_holdings(); idx,old=_find(rows,sell)
                if old is not None: old.update({"status":"closed","enabled":False,"closed_at":datetime.now(timezone.utc).isoformat()}); rows[idx]=old; _save_holdings(rows,sha,f"Close holding {sell}"); st.success(f"{sell} 전량 매도 처리 완료"); st.rerun()
            except Exception as e: st.error(str(e))


def install_holdings_tab():
    if getattr(st,"_hy_holdings_tab_installed",False): return
    original_tabs=st.tabs
    def wrapped_tabs(labels,*args,**kwargs):
        labels=list(labels); is_main="오늘 TOP12" in labels and "미국시장 스캔" in labels
        if is_main:
            extra=["🔥 5개월선 돌파","🧭 포트폴리오","🇺🇸 개별종목","📊 ETF","💼 보유종목"]
            containers=original_tabs(labels+extra,*args,**kwargs)
            with containers[-5]: render_monthly_breakout_tab()
            with containers[-4]: render_portfolio_tab()
            with containers[-3]: render_stock_tab()
            with containers[-2]: render_etf_tab()
            with containers[-1]: render_holdings_tab()
            return containers[:-5]
        return original_tabs(labels,*args,**kwargs)
    st.tabs=wrapped_tabs; st._hy_holdings_tab_installed=True

