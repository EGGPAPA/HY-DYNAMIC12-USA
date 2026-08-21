import os
from pathlib import Path
from dotenv import load_dotenv

ENV=Path(".env")
TOKEN=Path("data/token_us.json")

# KIS 키가 없는 Streamlit Cloud에서도 앱이 멈추지 않도록 사용하는 내부 표식입니다.
# 실제 API 비밀키가 아니며, 이 값이면 rank_us.py가 Yahoo Finance 후보발굴로 자동 전환합니다.
YAHOO_FALLBACK="__YAHOO_AUTO__"

def settings():
    load_dotenv(ENV,override=True)
    env=os.getenv("KIS_ENV","real").strip()
    key=os.getenv("KIS_APP_KEY","").strip()
    secret=os.getenv("KIS_APP_SECRET","").strip()
    return {
        "env":env,
        "key":key or YAHOO_FALLBACK,
        "secret":secret or YAHOO_FALLBACK,
        "account":os.getenv("KIS_ACCOUNT","").strip(),
        "product":os.getenv("KIS_PRODUCT","01").strip(),
        "base":"https://openapivts.koreainvestment.com:29443" if env!="real"
               else "https://openapi.koreainvestment.com:9443"
    }

def save(k,s,a,p,e):
    old=settings()
    old_key="" if old['key']==YAHOO_FALLBACK else old['key']
    old_secret="" if old['secret']==YAHOO_FALLBACK else old['secret']
    ENV.write_text(
        f"KIS_ENV={e}\n"
        f"KIS_APP_KEY={k or old_key}\n"
        f"KIS_APP_SECRET={s or old_secret}\n"
        f"KIS_ACCOUNT={a}\n"
        f"KIS_PRODUCT={p}\n", encoding="utf-8")
    if TOKEN.exists():
        TOKEN.unlink()
