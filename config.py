
import os
from pathlib import Path
from dotenv import load_dotenv

ENV=Path(".env")
TOKEN=Path("data/token_us.json")

def settings():
    load_dotenv(ENV,override=True)
    env=os.getenv("KIS_ENV","real").strip()
    return {
        "env":env,
        "key":os.getenv("KIS_APP_KEY","").strip(),
        "secret":os.getenv("KIS_APP_SECRET","").strip(),
        "account":os.getenv("KIS_ACCOUNT","").strip(),
        "product":os.getenv("KIS_PRODUCT","01").strip(),
        "base":"https://openapivts.koreainvestment.com:29443" if env!="real"
               else "https://openapi.koreainvestment.com:9443"
    }

def save(k,s,a,p,e):
    old=settings()
    ENV.write_text(
        f"KIS_ENV={e}\n"
        f"KIS_APP_KEY={k or old['key']}\n"
        f"KIS_APP_SECRET={s or old['secret']}\n"
        f"KIS_ACCOUNT={a}\n"
        f"KIS_PRODUCT={p}\n", encoding="utf-8")
    if TOKEN.exists():
        TOKEN.unlink()
