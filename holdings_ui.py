import base64
import json
import os
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st

from usa_asset_split_ui import render_stock_tab, render_etf_tab, ETF_UNIVERSE

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
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    pat = _github_pat()
    if pat:
        h["Authorization"] = f"Bearer {pat}"
    return h


def _load_holdings():
    r = requests.get(API_URL, headers=_headers(), params={"ref": BRANCH}, timeout=20)
    if r.status_code == 404:
        return [], None
    if r.status_code != 200:
        raise RuntimeError(f"holdings.json 읽기 실패: HTTP {r.status_code} / {r.text[:250]}")
    data = r.json()
    raw = base64.b64decode(data["content"]).decode("utf-8")
    rows = json.loads(raw or "[]")
    if not isinstance(rows, list):
        raise ValueError("holdings.json은 JSON 배열이어야 합니다.")
    return rows, data.get("sha")


def _save_holdings(rows, sha, message):
    if not _github_pat():
        raise RuntimeError("Streamlit Secrets에 GITHUB_PAT를 등록하세요.")
    text = json.dumps(rows, ensure_ascii=False, indent=2)
    payload = {
        "message": message,
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(API_URL, headers=_headers(), json=payload, timeout=20)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"holdings.json 저장 실패: HTTP {r.status_code} / {r.text[:250]}")


def _find(rows, ticker):
    t = ticker.strip().upper()
    for i, row in enumerate(rows):
        if str(row.get("ticker", "")).strip().upper() == t and str(row.get("status", "holding")).lower() != "closed":
            return i, row
    return None, None


def _asset_type(row):
    saved = str(row.get("asset_type", "")).strip().upper()
    if saved in {"STOCK", "ETF"}:
        return saved
    return "ETF" if str(row.get("ticker", "")).strip().upper() in ETF_UNIVERSE else "STOCK"


def _holding_table(rows, label):
    if not rows:
        st.info(f"현재 등록된 {label} 보유종목이 없습니다.")
        return
    view = []
    for r in rows:
        avg = float(r.get("average_price", 0) or 0)
        qty = float(r.get("quantity", 0) or 0)
        view.append({
            "구분": "ETF" if _asset_type(r) == "ETF" else "개별종목",
            "티커": r.get("ticker", ""),
            "종목명": r.get("name", ""),
            "평균매수가($)": round(avg, 4),
            "수량": qty,
            "투입금액($)": round(avg * qty, 2),
            "손절(-3%)": round(avg * .97, 2),
            "+15%": round(avg * 1.15, 2),
            "+20%": round(avg * 1.20, 2),
            "+25%": round(avg * 1.25, 2),
        })
    st.dataframe(pd.DataFrame(view), use_container_width=True, hide_index=True)


def render_holdings_tab():
    st.subheader("💼 미국 보유종목 관리")
    st.caption("KOR처럼 개별종목과 ETF를 구분해 관리합니다. 추가 매수 시 평균매수가를 자동 계산합니다.")

    try:
        rows, sha = _load_holdings()
    except Exception as e:
        st.error(str(e))
        rows, sha = [], None

    active = [x for x in rows if str(x.get("status", "holding")).lower() != "closed" and x.get("enabled", True)]
    stock_holdings = [x for x in active if _asset_type(x) == "STOCK"]
    etf_holdings = [x for x in active if _asset_type(x) == "ETF"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("전체 보유", len(active))
    c2.metric("개별종목", len(stock_holdings))
    c3.metric("ETF", len(etf_holdings))
    c4.metric("GitHub 저장", "준비됨" if _github_pat() else "PAT 미설정")

    h1, h2 = st.tabs(["🇺🇸 개별종목 보유", "📊 ETF 보유"])
    with h1:
        _holding_table(stock_holdings, "개별종목")
    with h2:
        _holding_table(etf_holdings, "ETF")

    with st.form("hy_holding_buy_form", clear_on_submit=False):
        st.markdown("#### 매수 등록 / 추가 매수")
        a0, a, b = st.columns([0.8, 1, 2])
        asset_type = a0.selectbox("구분", ["개별종목", "ETF"], key="hy_hold_asset_type")
        ticker = a.text_input("티커", placeholder="예: NVDA / QQQ", key="hy_hold_ticker").strip().upper()
        name = b.text_input("종목명", placeholder="예: NVIDIA / Invesco QQQ", key="hy_hold_name").strip()
        c, d = st.columns(2)
        buy_price = c.number_input("실제 체결 매수가($)", min_value=0.0, step=0.01, format="%.4f", key="hy_hold_price")
        buy_qty = d.number_input("매수 수량", min_value=0.0, step=1.0, format="%.4f", key="hy_hold_qty")
        submitted = st.form_submit_button("➕ 보유 등록 / 추가 매수", type="primary", use_container_width=True)

    if submitted:
        if not ticker or buy_price <= 0 or buy_qty <= 0:
            st.error("티커, 실제 체결 매수가, 수량을 입력하세요.")
        else:
            try:
                rows, sha = _load_holdings()
                idx, old = _find(rows, ticker)
                now = datetime.now(timezone.utc).isoformat()
                kind = "ETF" if asset_type == "ETF" else "STOCK"
                if old is None:
                    new_avg = float(buy_price)
                    new_qty = float(buy_qty)
                    rows.append({
                        "ticker": ticker,
                        "name": name or ticker,
                        "asset_type": kind,
                        "mode": "holding",
                        "status": "holding",
                        "average_price": round(new_avg, 6),
                        "quantity": round(new_qty, 6),
                        "stop_loss_pct": 3,
                        "enabled": True,
                        "updated_at": now,
                    })
                    msg = f"Add {kind} holding {ticker}"
                else:
                    old_avg = float(old.get("average_price", 0) or 0)
                    old_qty = float(old.get("quantity", 0) or 0)
                    new_qty = old_qty + float(buy_qty)
                    new_avg = ((old_avg * old_qty) + (float(buy_price) * float(buy_qty))) / new_qty
                    old.update({
                        "name": name or old.get("name") or ticker,
                        "asset_type": kind,
                        "mode": "holding",
                        "status": "holding",
                        "average_price": round(new_avg, 6),
                        "quantity": round(new_qty, 6),
                        "stop_loss_pct": float(old.get("stop_loss_pct", 3) or 3),
                        "enabled": True,
                        "updated_at": now,
                    })
                    rows[idx] = old
                    msg = f"Update {kind} holding {ticker}"
                _save_holdings(rows, sha, msg)
                st.success(f"{ticker} 저장 완료 · {asset_type} · 평균매수가 ${new_avg:,.4f} · 총수량 {new_qty:g}")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.markdown("#### 전량 매도 처리")
    active_tickers = [str(x.get("ticker", "")).strip().upper() for x in active if x.get("ticker")]
    if active_tickers:
        sell_ticker = st.selectbox("전량 매도할 종목", active_tickers, key="hy_hold_close_ticker")
        if st.button("✅ 전량 매도 → 감시 종료", use_container_width=True, key="hy_hold_close_btn"):
            try:
                rows, sha = _load_holdings()
                idx, old = _find(rows, sell_ticker)
                if old is None:
                    st.warning("해당 보유종목을 찾지 못했습니다.")
                else:
                    old["status"] = "closed"
                    old["enabled"] = False
                    old["closed_at"] = datetime.now(timezone.utc).isoformat()
                    rows[idx] = old
                    _save_holdings(rows, sha, f"Close holding {sell_ticker}")
                    st.success(f"{sell_ticker} 전량 매도 처리 완료 · 자동감시 종료")
                    st.rerun()
            except Exception as e:
                st.error(str(e))
    else:
        st.caption("전량 매도 처리할 보유종목이 없습니다.")

    st.info("개별종목과 ETF 모두 TOP12에서 빠져도 holdings.json에 남고, 보유 기준 -3%, +15%, +20%, +25%를 계속 관리할 수 있습니다.")


def install_holdings_tab():
    if getattr(st, "_hy_holdings_tab_installed", False):
        return
    original_tabs = st.tabs

    def wrapped_tabs(labels, *args, **kwargs):
        labels = list(labels)

        # 메인 USA 앱 탭에는 개별종목 / ETF를 별도 탭으로 추가한다.
        is_main = "오늘 TOP12" in labels and "미국시장 스캔" in labels
        if is_main:
            extra = ["🇺🇸 개별종목", "📊 ETF", "💼 보유종목"]
            containers = original_tabs(labels + extra, *args, **kwargs)
            with containers[-3]:
                render_stock_tab()
            with containers[-2]:
                render_etf_tab()
            with containers[-1]:
                render_holdings_tab()
            return containers[:-3]

        # 다른 탭 그룹에는 기존 방식대로 보유종목 탭만 자동 추가한다.
        if "💼 보유종목" in labels:
            return original_tabs(labels, *args, **kwargs)
        containers = original_tabs(labels + ["💼 보유종목"], *args, **kwargs)
        with containers[-1]:
            render_holdings_tab()
        return containers[:-1]

    st.tabs = wrapped_tabs
    st._hy_holdings_tab_installed = True
