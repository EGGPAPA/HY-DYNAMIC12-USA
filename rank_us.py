import pandas as pd
import yfinance as yf
import io
import requests


def _num(v):
    try:return float(str(v).replace(",","").replace("%","").strip() or 0)
    except:return 0.0

def _pick(r,keys,default=""):
    for k in keys:
        if k in r and str(r.get(k,"")).strip() not in ("","None"):
            return r.get(k)
    return default


# KIS 미설정 시 자동으로 검사하는 미국 핵심 유동성 종목군.
# NASDAQ / NYSE / AMEX 대표 대형주·성장주·주도주를 넓게 포함하고,
# 이후 기존 HY DYNAMIC12 정밀분석(Yahoo 일봉/재무/기술)이 TOP12를 다시 선별합니다.
YAHOO_UNIVERSE={
    "NAS":[
        "AAPL","MSFT","NVDA","AMZN","GOOGL","GOOG","META","AVGO","TSLA","NFLX",
        "AMD","INTC","QCOM","MU","ARM","ASML","AMAT","LRCX","KLAC","MRVL",
        "PLTR","CRWD","PANW","FTNT","ZS","DDOG","MDB","SNOW","APP","HOOD",
        "COIN","MSTR","PYPL","ADBE","ORCL","CSCO","INTU","BKNG","COST","PEP",
        "AMGN","GILD","VRTX","REGN","ISRG","ADP","MELI","ABNB","DASH","CEG"
    ],
    "NYS":[
        "BRK-B","JPM","V","MA","WMT","LLY","UNH","XOM","CVX","GE","CAT","BA",
        "RTX","LMT","NOC","GD","DE","ETN","PH","UBER","CRM","NOW","IBM","ACN",
        "GS","MS","BAC","WFC","C","AXP","BLK","SPGI","MCO","DIS","NKE","TMO",
        "ABBV","MRK","JNJ","PFE","HD","LOW","TJX","ORCL","F","GM","RBLX","NET",
        "VRT","ANET"
    ],
    "AMS":["SPY","QQQ","IWM","DIA","SOXL","TQQQ","ARKK","SMH","XLK","XLE"]
}

SP500_CSV="https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"


def _broad_universe():
    """S&P500 전체와 기존 성장/주도주 후보를 합친 500~650개 유동성 종목군."""
    names={}
    exchanges={}
    try:
        response=requests.get(SP500_CSV,timeout=20)
        response.raise_for_status()
        frame=pd.read_csv(io.StringIO(response.text))
        for _,row in frame.iterrows():
            symbol=str(row.get("Symbol","")).strip().upper().replace(".","-")
            if symbol:
                names[symbol]=str(row.get("Security") or symbol)
                exchanges[symbol]="USA"
    except Exception:
        pass
    for exchange,items in YAHOO_UNIVERSE.items():
        for symbol in items:
            names.setdefault(symbol,symbol);exchanges.setdefault(symbol,exchange)
    return names,exchanges


def broad_us_candidates(candidate_n=120):
    """미국 핵심 유동성 종목 500개 이상을 배치 조회해 정밀분석 후보를 압축한다."""
    names,exchanges=_broad_universe();symbols=list(names);rows=[];errors=[];chunk_size=80
    for start in range(0,len(symbols),chunk_size):
        chunk=symbols[start:start+chunk_size]
        try:
            data=yf.download(chunk,period="6mo",interval="1d",auto_adjust=False,progress=False,threads=8,group_by="ticker")
        except Exception as e:
            errors.append(f"Yahoo broad {start+1}-{start+len(chunk)}: {type(e).__name__}");continue
        for symbol in chunk:
            try:
                daily=data[symbol] if isinstance(data.columns,pd.MultiIndex) else data
                close=pd.to_numeric(daily["Close"],errors="coerce").dropna();volume=pd.to_numeric(daily["Volume"],errors="coerce").reindex(close.index).dropna()
                if len(close)<61 or len(volume)<20:continue
                price=float(close.iloc[-1]);avg_dollar=float((close.tail(20)*volume.tail(20)).mean())
                if price<3 or avg_dollar<50_000_000:continue
                r5=(price/float(close.iloc[-6])-1)*100;r20=(price/float(close.iloc[-21])-1)*100;r60=(price/float(close.iloc[-61])-1)*100
                volume_ratio=float(volume.tail(5).mean()/max(volume.tail(20).mean(),1));near_high=price/float(close.tail(120).max())*100
                liquidity=min(100,max(0,(__import__('math').log10(max(avg_dollar,1))-7)*35))
                momentum=min(100,max(0,50+r5*.8+r20*1.5+r60*.35));volume_score=min(100,max(0,50+(volume_ratio-1)*35));high_score=min(100,max(0,near_high))
                score=round(liquidity*.30+momentum*.35+volume_score*.15+high_score*.20,1)
                rows.append({"symbol":symbol,"name":names[symbol],"exchange":exchanges[symbol],"sources":"S&P500+성장주/유동성/모멘텀/거래증가/고점","source_count":4,"pre_score":score})
            except Exception:continue
    if not rows:
        fallback,_=_yahoo_candidates(candidate_n)
        return fallback,["광범위 스캔 실패 · 기존 유동성 후보군으로 대체"]+errors
    frame=pd.DataFrame(rows).sort_values("pre_score",ascending=False).drop_duplicates("symbol")
    return frame.head(int(candidate_n)).reset_index(drop=True),errors


def _yahoo_candidates(candidate_n=40):
    """KIS 키 없이 Yahoo Finance만으로 1차 후보를 만듭니다."""
    symbols=[]
    exchange={}
    for excd,items in YAHOO_UNIVERSE.items():
        for sym in items:
            if sym not in exchange:
                symbols.append(sym); exchange[sym]=excd

    rows=[]
    try:
        data=yf.download(symbols,period="3mo",interval="1d",auto_adjust=False,
                         progress=False,threads=True,group_by="ticker")
    except Exception:
        data=None

    for sym in symbols:
        try:
            if data is None or len(data)==0: continue
            d=data[sym] if isinstance(data.columns,pd.MultiIndex) else data
            close=pd.to_numeric(d["Close"],errors="coerce").dropna()
            vol=pd.to_numeric(d["Volume"],errors="coerce").dropna()
            if len(close)<20 or len(vol)<20: continue
            px=float(close.iloc[-1])
            r20=(px/float(close.iloc[-21])-1)*100 if len(close)>=21 else 0
            r5=(px/float(close.iloc[-6])-1)*100 if len(close)>=6 else 0
            avgvol=float(vol.tail(20).mean()) or 1
            vr=float(vol.iloc[-1])/avgvol
            dollar=px*float(vol.iloc[-1])
            high=float(close.tail(60).max())
            near=px/high*100 if high else 0
            # 유동성 + 최근 모멘텀 + 거래량 증가 + 고점 접근을 1차 점수로 사용
            liquidity=min(100,max(0,20*(0 if dollar<=0 else __import__('math').log10(max(dollar,1))-5)))
            momentum=min(100,max(0,50+r20*2.0+r5*1.0))
            volume_score=min(100,max(0,vr*45))
            high_score=min(100,max(0,near))
            score=round(liquidity*.30+momentum*.30+volume_score*.20+high_score*.20,1)
            rows.append({
                "symbol":sym,"name":sym,"exchange":exchange[sym],
                "sources":"Yahoo자동/거래대금/모멘텀/거래증가/고점",
                "source_count":4,"pre_score":score
            })
        except Exception:
            continue

    if not rows:
        raise RuntimeError("Yahoo Finance 미국시장 후보 데이터를 만들지 못했습니다. 잠시 후 다시 실행하세요.")
    return pd.DataFrame(rows).sort_values("pre_score",ascending=False).head(int(candidate_n)).reset_index(drop=True),[]


class USScanner:
    def __init__(self,api): self.api=api

    def normalize(self,rows,excd,source,topn=30):
        out=[]
        for rank,r in enumerate((rows or [])[:topn],1):
            sym=str(_pick(r,["symb","SYMB","rsym","ticker","pdno"])).strip()
            name=str(_pick(r,["name","ename","knam","hname","symb"],sym)).strip()
            if not sym: continue
            price=_num(_pick(r,["last","clos","price","stck_prpr"]))
            change=_num(_pick(r,["rate","diff","prdy_ctrt","change_rate"]))
            out.append({"symbol":sym,"name":name,"exchange":excd,"source":source,
                        "source_rank":rank,"price":price,"change_pct":change})
        return out

    def candidates(self,candidate_n=40,per_source=25):
        # Streamlit Cloud에서 KIS 키가 없으면 별도 설정을 요구하지 않고 Yahoo로 자동 전환
        if str(self.api.s.get("key","")).startswith("__YAHOO_AUTO__"):
            return _yahoo_candidates(candidate_n)

        rows=[]; errors=[]
        for excd in ["NAS","NYS","AMS"]:
            for source,fn in [("거래대금",self.api.trade_value),("시가총액",self.api.market_cap),
                              ("거래증가",self.api.trade_growth),("신고가",self.api.new_high)]:
                try: rows+=self.normalize(fn(excd),excd,source,per_source)
                except Exception as e: errors.append(f"{excd} {source}: {e}")
        if not rows:
            # KIS가 일시적으로 실패해도 사용자가 키를 다시 입력할 필요 없이 Yahoo로 계속 진행
            return _yahoo_candidates(candidate_n)
        df=pd.DataFrame(rows)
        result=[]
        weights={"거래대금":1.0,"거래증가":.9,"신고가":.9,"시가총액":.55}
        for (sym,excd),g in df.groupby(["symbol","exchange"],sort=False):
            score=sum(max(0,101-r.source_rank*3)*weights.get(r.source,.5) for _,r in g.iterrows())
            src=set(g.source); score=min(100,score/2+max(0,len(src)-1)*15)
            result.append({"symbol":sym,"name":g.iloc[0]["name"],
                           "exchange":excd,"sources":"/".join(sorted(src)),
                           "source_count":len(src),"pre_score":round(score,1)})
        x=pd.DataFrame(result).sort_values(["pre_score","source_count"],ascending=False)
        return x.head(int(candidate_n)).reset_index(drop=True),errors

