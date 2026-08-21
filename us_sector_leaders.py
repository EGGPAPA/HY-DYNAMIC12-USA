import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


NEW_YORK = ZoneInfo("America/New_York")

SECTOR_GROUPS = {
    "AI·소프트웨어": ["MSFT","ORCL","CRM","NOW","ADBE","PLTR","SNOW","DDOG","MDB","APP","IBM","ACN"],
    "반도체·네트워크": ["NVDA","AVGO","AMD","INTC","QCOM","MU","ARM","ASML","AMAT","LRCX","KLAC","MRVL","ANET","CSCO"],
    "사이버보안": ["CRWD","PANW","FTNT","ZS","NET"],
    "인터넷·플랫폼": ["AMZN","META","GOOGL","GOOG","NFLX","MELI","RBLX"],
    "여행·레저": ["BKNG","ABNB","DASH","DIS","UBER"],
    "결제·핀테크": ["V","MA","PYPL","HOOD","COIN","MSTR","INTU"],
    "금융·자산관리": ["JPM","BAC","WFC","C","GS","MS","BLK","SPGI","MCO","AXP","BRK-B"],
    "헬스케어": ["LLY","UNH","AMGN","GILD","VRTX","REGN","ISRG","ABBV","MRK","JNJ","PFE","TMO"],
    "산업재·방산": ["GE","CAT","BA","RTX","LMT","NOC","GD","DE","ETN","PH"],
    "소비·유통": ["AAPL","WMT","COST","HD","LOW","TJX","NKE","PEP"],
    "자동차": ["TSLA","F","GM"],
    "에너지·전력": ["XOM","CVX","CEG","VRT"],
}


def _market_date():
    return datetime.now(timezone.utc).astimezone(NEW_YORK).date()


def scan_sector_leaders(max_sectors=5, representatives=3, require_today=False):
    symbols=list(dict.fromkeys(sym for members in SECTOR_GROUPS.values() for sym in members))
    data=yf.download(symbols,period="6mo",interval="1d",auto_adjust=True,
                     progress=False,threads=True,group_by="ticker")
    forced=os.environ.get("FORCE_RUN","").lower() in {"1","true","yes"}
    stocks=[]
    for sector,members in SECTOR_GROUPS.items():
        for ticker in members:
            try:
                d=data[ticker] if isinstance(data.columns,pd.MultiIndex) else data
                close=pd.to_numeric(d["Close"],errors="coerce").dropna()
                volume=pd.to_numeric(d["Volume"],errors="coerce").reindex(close.index).dropna()
                if len(close)<61 or len(volume)<20:
                    continue
                latest_date=pd.Timestamp(close.index[-1]).date()
                if require_today and not forced and latest_date != _market_date():
                    continue
                price=float(close.iloc[-1]); ma20=float(close.tail(20).mean()); ma60=float(close.tail(60).mean())
                r20=(price/float(close.iloc[-21])-1)*100
                r60=(price/float(close.iloc[-61])-1)*100
                vr=float(volume.tail(5).mean()/max(volume.tail(20).mean(),1))
                ma20_series=close.rolling(20).mean()
                ma60_series=close.rolling(60).mean()
                r20_series=close.pct_change(20)*100
                leader_flags=(close>ma20_series)&(ma20_series>ma60_series)&(r20_series>=5)
                leader_days=0
                for flag in reversed(leader_flags.fillna(False).tolist()):
                    if not flag:
                        break
                    leader_days+=1
                leader_start=(
                    pd.Timestamp(close.index[-leader_days]).strftime("%Y-%m-%d")
                    if leader_days else "-"
                )
                observation=ma20*1.02; invalidation=ma60*.97
                checks={
                    "near_observation":abs(price/observation-1)<=.02,
                    "above_ma20":price>=ma20,
                    "volume_ok":vr>=.7,
                    "above_invalidation":price>invalidation,
                }
                trend=price>ma20>ma60
                score=min(100,max(0,45+r20*1.15+r60*.30+min(vr,2)*7+(8 if trend else 0)))
                stocks.append({
                    "sector":sector,"ticker":ticker,"price":price,"ma20":ma20,"ma60":ma60,
                    "return20":r20,"return60":r60,"volume_ratio":vr,
                    "observation":observation,"invalidation":invalidation,
                    "trend":trend,"ready":trend and r20>=5 and all(checks.values()),
                    "leader_start":leader_start,"leader_days":leader_days,
                    "score":score,**checks,
                })
            except Exception:
                continue

    sectors=[]
    for sector in SECTOR_GROUPS:
        members=[x for x in stocks if x["sector"]==sector]
        if len(members)<2:
            continue
        avg20=sum(x["return20"] for x in members)/len(members)
        avg60=sum(x["return60"] for x in members)/len(members)
        breadth=sum(x["trend"] for x in members)/len(members)*100
        volume=sum(x["volume_ratio"] for x in members)/len(members)
        sector_score=max(0,min(100,50+avg20*1.1+avg60*.35+(breadth-50)*.25+min(volume,2)*5))
        strength="강세" if sector_score>=70 and avg20>0 else "중립" if sector_score>=55 else "약세"
        reps=sorted(
            [x for x in members if x["trend"] and x["return20"]>=0],
            key=lambda x:(x["ready"],x["score"]),reverse=True
        )[:representatives]
        sectors.append({
            "sector":sector,"score":sector_score,"return20":avg20,"return60":avg60,
            "breadth":breadth,"volume_ratio":volume,"strength":strength,"representatives":reps,
        })
    sectors.sort(key=lambda x:x["score"],reverse=True)
    selected=[x for x in sectors if x["strength"]!="약세"][:max_sectors]
    return selected

