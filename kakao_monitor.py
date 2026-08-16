import os
import json
import requests
import yfinance as yf
from datetime import datetime, timezone
from pathlib import Path

WATCHLIST_FILE = Path("kakao_watchlist.json")
STATE_DIR = Path("data")
STATE_FILE = STATE_DIR / "kakao_monitor_state.json"

KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")
KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "")
KAKAO_REFRESH_TOKEN = os.environ.get("KAKAO_REFRESH_TOKEN", "")

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def load_json(path, default):
    if not path.exists():
        return default

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_access_token():
    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": KAKAO_REFRESH_TOKEN,
    }

    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = KAKAO_CLIENT_SECRET

    r = requests.post(TOKEN_URL, data=data, timeout=20)
    r.raise_for_status()

    result = r.json()

    if "access_token" not in result:
        raise RuntimeError(f"카카오 토큰 갱신 실패: {result}")

    return result["access_token"]


def send_kakao(access_token, text):
    template = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": os.environ.get("APP_URL", "https://streamlit.io"),
            "mobile_web_url": os.environ.get(
                "APP_URL", "https://streamlit.io"
            ),
        },
        "button_title": "HY DYNAMIC12 열기",
    }

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    data = {
        "template_object": json.dumps(
            template,
            ensure_ascii=False
        )
    }

    r = requests.post(
        MEMO_URL,
        headers=headers,
        data=data,
        timeout=20
    )

    if r.status_code != 200:
        raise RuntimeError(
            f"카카오 메시지 전송 실패: {r.status_code} {r.text}"
        )


def get_price(ticker):
    obj = yf.Ticker(ticker)

    hist = obj.history(
        period="1d",
        interval="1m",
        prepost=False
    )

    if hist.empty:
        hist = obj.history(period="5d")

    if hist.empty:
        return None

    return float(hist["Close"].dropna().iloc[-1])


def main():
    if not WATCHLIST_FILE.exists():
        raise FileNotFoundError(
            "kakao_watchlist.json 파일을 찾을 수 없습니다."
        )

    watchlist = load_json(WATCHLIST_FILE, [])
    state = load_json(STATE_FILE, {})

    if not isinstance(watchlist, list):
        raise ValueError(
            "kakao_watchlist.json은 JSON 배열이어야 합니다."
        )

    access_token = None
    changed = False

    for item in watchlist:
        if not item.get("enabled", True):
            continue

        ticker = str(item.get("ticker", "")).strip().upper()
        name = str(item.get("name", ticker)).strip()

        if not ticker:
            continue

        price = get_price(ticker)

        if price is None:
            print(f"{ticker}: 가격 조회 실패")
            continue

        print(f"{ticker}: ${price:.2f}")

        levels = [
            ("entry1", "1차 매수가"),
            ("entry2", "2차 매수가"),
        ]

        for key, label in levels:
            target = item.get(key)

            if target in (None, ""):
                continue

            target = float(target)
            state_key = f"{ticker}_{key}"

            # 매수가 이하로 내려오면 알림
            if price <= target:
                if not state.get(state_key, False):

                    if access_token is None:
                        access_token = get_access_token()

                    message = (
                        f"🔔 HY DYNAMIC12 매수가 도달\n\n"
                        f"종목: {name} ({ticker})\n"
                        f"단계: {label}\n"
                        f"현재가: ${price:.2f}\n"
                        f"목표 매수가: ${target:.2f}\n\n"
                        f"HY DYNAMIC12 자동감시"
                    )

                    send_kakao(access_token, message)

                    state[state_key] = True
                    changed = True

                    print(
                        f"{ticker} {label} 카카오 알림 전송 완료"
                    )

            # 가격이 다시 목표가 위로 올라가면 재무장
            else:
                if state.get(state_key, False):
                    state[state_key] = False
                    changed = True

    if changed:
        state["_updated_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        save_json(STATE_FILE, state)

    print("HY DYNAMIC12 자동감시 완료")


if __name__ == "__main__":
    main()
