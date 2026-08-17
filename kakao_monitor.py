import os
import json
import requests
import yfinance as yf
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

WATCHLIST_FILE = Path("kakao_watchlist.json")
HOLDINGS_FILE = Path("holdings.json")
STATE_FILE = Path("data/kakao_monitor_state.json")

KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "").strip()
KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
KAKAO_REFRESH_TOKEN = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
APP_URL = os.environ.get(
    "APP_URL",
    "https://eggpapa-hy-dynamic12-usa-app-s7ppvp.streamlit.app",
)

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
NEW_YORK = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def ny_now():
    return datetime.now(timezone.utc).astimezone(NEW_YORK)


def is_us_regular_market_time():
    now = ny_now()
    if now.weekday() >= 5:
        return False
    local_time = now.time().replace(tzinfo=None)
    return MARKET_OPEN <= local_time <= MARKET_CLOSE


def load_json(path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"{path} 읽기 실패: {e}")
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_access_token():
    if not KAKAO_REST_API_KEY or not KAKAO_REFRESH_TOKEN:
        raise RuntimeError("KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN 미설정")
    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": KAKAO_REFRESH_TOKEN,
    }
    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = KAKAO_CLIENT_SECRET
    r = requests.post(TOKEN_URL, data=data, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"카카오 토큰 갱신 실패: HTTP {r.status_code} / {r.text}")
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("카카오 access_token 없음")
    return token


def send_kakao(access_token, text):
    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": APP_URL, "mobile_web_url": APP_URL},
        "button_title": "HY DYNAMIC12 열기",
    }
    r = requests.post(
        MEMO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"카카오 메시지 전송 실패: HTTP {r.status_code} / {r.text}")


def get_price(ticker):
    try:
        obj = yf.Ticker(ticker)
        hist = obj.history(period="1d", interval="1m", prepost=False)
        if hist.empty:
            hist = obj.history(period="5d")
        if hist.empty:
            return None
        close = hist["Close"].dropna()
        return None if close.empty else float(close.iloc[-1])
    except Exception as e:
        print(f"{ticker}: 가격 조회 오류 {e}")
        return None


def alert_once(access_token, state, key, condition, reset_condition, message):
    changed = False
    if condition:
        if not state.get(key, False):
            if access_token is None:
                access_token = get_access_token()
            send_kakao(access_token, message)
            state[key] = True
            changed = True
    elif reset_condition and state.get(key, False):
        state[key] = False
        changed = True
    return access_token, changed


def monitor_candidate(item, price, state, access_token):
    ticker = str(item.get("ticker", "")).strip().upper()
    name = str(item.get("name", ticker)).strip()
    changed = False
    for field, label in (("entry1", "1차 매수가"), ("entry2", "2차 매수가")):
        raw = item.get(field)
        if raw in (None, ""):
            continue
        target = float(raw)
        key = f"candidate:{ticker}:{field}"
        msg = (
            "🔔 HY DYNAMIC12 매수가 도달\n\n"
            f"종목: {name} ({ticker})\n"
            f"단계: {label}\n"
            f"현재가: ${price:.2f}\n"
            f"목표 매수가: ${target:.2f}\n\n"
            "매수 전 후보 자동감시"
        )
        access_token, c = alert_once(
            access_token, state, key,
            price <= target,
            price > target,
            msg,
        )
        changed = changed or c
    return access_token, changed


def monitor_holding(item, price, state, access_token):
    ticker = str(item.get("ticker", "")).strip().upper()
    name = str(item.get("name", ticker)).strip()
    avg_raw = item.get("average_price")
    if avg_raw in (None, ""):
        print(f"{ticker}: 보유종목 average_price 없음 → 건너뜀")
        return access_token, False

    avg = float(avg_raw)
    changed = False

    profit_levels = [
        (15.0, "+15% 1차 익절"),
        (20.0, "+20% 추가 익절"),
        (25.0, "+25% 추가 익절"),
    ]
    for pct, label in profit_levels:
        target = avg * (1 + pct / 100.0)
        key = f"holding:{ticker}:profit:{int(pct)}"
        msg = (
            "🎯 HY DYNAMIC12 보유종목 목표수익 도달\n\n"
            f"종목: {name} ({ticker})\n"
            f"단계: {label}\n"
            f"평균매수가: ${avg:.2f}\n"
            f"현재가: ${price:.2f}\n"
            f"목표가: ${target:.2f}\n\n"
            "분할매도 여부를 확인하세요."
        )
        access_token, c = alert_once(
            access_token, state, key,
            price >= target,
            price < target,
            msg,
        )
        changed = changed or c

    stop_pct = abs(float(item.get("stop_loss_pct", 3) or 3))
    stop = avg * (1 - stop_pct / 100.0)
    key = f"holding:{ticker}:stop"
    msg = (
        "⚠️ HY DYNAMIC12 보유종목 손절 기준 도달\n\n"
        f"종목: {name} ({ticker})\n"
        f"평균매수가: ${avg:.2f}\n"
        f"현재가: ${price:.2f}\n"
        f"손절 기준가: ${stop:.2f} (-{stop_pct:.1f}%)\n\n"
        "보유 여부를 확인하세요."
    )
    access_token, c = alert_once(
        access_token, state, key,
        price <= stop,
        price > stop,
        msg,
    )
    changed = changed or c
    return access_token, changed


def main():
    now = ny_now()
    print("=== HY DYNAMIC12 Kakao Monitor 시작 ===")
    print("뉴욕 현재시간:", now.strftime("%Y-%m-%d %H:%M:%S %Z"))

    if not is_us_regular_market_time():
        print("미국 정규장 09:30~16:00 ET가 아니므로 종료")
        return

    watchlist = load_json(WATCHLIST_FILE, [])
    holdings = load_json(HOLDINGS_FILE, [])
    state = load_json(STATE_FILE, {})

    if not isinstance(watchlist, list):
        raise ValueError("kakao_watchlist.json은 JSON 배열이어야 합니다.")
    if not isinstance(holdings, list):
        raise ValueError("holdings.json은 JSON 배열이어야 합니다.")

    active_holdings = []
    held_tickers = set()
    for item in holdings:
        status = str(item.get("status", "holding")).strip().lower()
        if status == "closed" or not item.get("enabled", True):
            continue
        ticker = str(item.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        held_tickers.add(ticker)
        active_holdings.append(item)

    access_token = None
    changed = False

    print(f"매수 전 후보 {len(watchlist)}종목 / 보유종목 {len(active_holdings)}종목")

    # 실제 보유 중인 종목은 TOP12/watchlist에서 빠져도 holdings.json을 기준으로 계속 감시합니다.
    for item in active_holdings:
        ticker = str(item.get("ticker", "")).strip().upper()
        price = get_price(ticker)
        if price is None:
            print(f"{ticker}: 보유종목 가격 조회 실패")
            continue
        print(f"[보유] {ticker} 현재가 ${price:.2f}")
        access_token, c = monitor_holding(item, price, state, access_token)
        changed = changed or c

    # 이미 보유 중인 종목은 candidate 알림을 중복 전송하지 않습니다.
    for item in watchlist:
        if not item.get("enabled", True):
            continue
        ticker = str(item.get("ticker", "")).strip().upper()
        if not ticker or ticker in held_tickers:
            continue
        price = get_price(ticker)
        if price is None:
            print(f"{ticker}: 후보 가격 조회 실패")
            continue
        print(f"[후보] {ticker} 현재가 ${price:.2f}")
        access_token, c = monitor_candidate(item, price, state, access_token)
        changed = changed or c

    if changed:
        save_json(STATE_FILE, state)
        print("알림 상태 저장 완료")
    else:
        print("알림 상태 변경 없음")

    print("=== HY DYNAMIC12 자동감시 종료 ===")


if __name__ == "__main__":
    main()
