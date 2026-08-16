import os
import json
import requests
import yfinance as yf
from datetime import datetime, timezone
from pathlib import Path

WATCHLIST_FILE = Path("kakao_watchlist.json")
STATE_DIR = Path("data")
STATE_FILE = STATE_DIR / "kakao_monitor_state.json"

KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "").strip()
KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
KAKAO_REFRESH_TOKEN = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()

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


def validate_secrets():
    missing = []
    if not KAKAO_REST_API_KEY:
        missing.append("KAKAO_REST_API_KEY")
    if not KAKAO_REFRESH_TOKEN:
        missing.append("KAKAO_REFRESH_TOKEN")
    if missing:
        raise RuntimeError(
            "GitHub Repository Secrets 누락: " + ", ".join(missing)
        )


def get_access_token():
    validate_secrets()

    data = {
        "grant_type": "refresh_token",
        "client_id": KAKAO_REST_API_KEY,
        "refresh_token": KAKAO_REFRESH_TOKEN,
    }

    if KAKAO_CLIENT_SECRET:
        data["client_secret"] = KAKAO_CLIENT_SECRET

    r = requests.post(TOKEN_URL, data=data, timeout=20)

    if r.status_code != 200:
        raise RuntimeError(
            f"카카오 토큰 갱신 실패: HTTP {r.status_code} / {r.text}"
        )

    result = r.json()
    access_token = result.get("access_token")

    if not access_token:
        raise RuntimeError(
            f"카카오 access_token 없음: {result}"
        )

    if result.get("refresh_token"):
        print(
            "주의: 카카오가 새 refresh_token을 반환했습니다. "
            "필요하면 Streamlit/GitHub Secret 값을 갱신하세요."
        )

    return access_token


def send_kakao(access_token, text):
    app_url = os.environ.get(
        "APP_URL",
        "https://eggpapa-hy-dynamic12-usa-app-s7ppvp.streamlit.app"
    )

    template = {
        "object_type": "text",
        "text": text,
        "link": {
            "web_url": app_url,
            "mobile_web_url": app_url,
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
            f"카카오 메시지 전송 실패: HTTP {r.status_code} / {r.text}"
        )

    print("카카오 메시지 전송 성공")


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

    close = hist["Close"].dropna()

    if close.empty:
        return None

    return float(close.iloc[-1])


def main():
    print("=== HY DYNAMIC12 Kakao Monitor 시작 ===")

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
    enabled_count = 0

    for item in watchlist:
        if not item.get("enabled", True):
            continue

        enabled_count += 1

        ticker = str(item.get("ticker", "")).strip().upper()
        name = str(item.get("name", ticker)).strip()

        if not ticker:
            print("ticker 없는 항목 건너뜀")
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

            print(
                f"{ticker} {label}: "
                f"현재 ${price:.2f} / 기준 ${target:.2f}"
            )

            if price <= target:
                if not state.get(state_key, False):
                    print(
                        f"{ticker} {label} 도달 → 카카오 알림 준비"
                    )

                    if access_token is None:
                        access_token = get_access_token()

                    message = (
                        "🔔 HY DYNAMIC12 매수가 도달\n\n"
                        f"종목: {name} ({ticker})\n"
                        f"단계: {label}\n"
                        f"현재가: ${price:.2f}\n"
                        f"목표 매수가: ${target:.2f}\n\n"
                        "HY DYNAMIC12 자동감시"
                    )

                    send_kakao(access_token, message)

                    state[state_key] = True
                    changed = True

                    print(
                        f"{ticker} {label} 알림 상태 저장"
                    )

                else:
                    print(
                        f"{ticker} {label}: 이미 알림 전송된 상태"
                    )

            else:
                if state.get(state_key, False):
                    state[state_key] = False
                    changed = True

                    print(
                        f"{ticker} {label}: 가격 회복 → 알림 재무장"
                    )

    if enabled_count == 0:
        print("활성화된 감시 종목이 없습니다.")

    if changed:
        state["_updated_at"] = datetime.now(
            timezone.utc
        ).isoformat()

        save_json(STATE_FILE, state)
        print(f"상태 파일 저장: {STATE_FILE}")
    else:
        print("상태 변경 없음")

    print("=== HY DYNAMIC12 자동감시 완료 ===")


if __name__ == "__main__":
    main()
