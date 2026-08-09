
import json,time,requests,pandas as pd
from pathlib import Path
from datetime import datetime,timedelta
import yfinance as yf
from config import TOKEN

CACHE=Path("data/cache"); CACHE.mkdir(parents=True,exist_ok=True)

def _num(v):
    try:return float(str(v).replace(",","").replace("%","").strip() or 0)
    except:return 0.0


def yf_symbol(symb):
    """KIS 미국 종목코드를 Yahoo Finance 표기에 맞춥니다."""
    s=str(symb).strip().upper()
    # Yahoo는 클래스주를 BRK-B, BF-B 형식으로 사용
    if "/" in s:
        s=s.replace("/", "-")
    return s

def yf_daily(symb, min_rows=120):
    """정밀분석용 일봉. KIS와 분리하여 yfinance에서 직접 확보."""
    ys=yf_symbol(symb)
    cp=CACHE/f"YF_{ys.replace('/','_')}.csv"

    if cp.exists() and time.time()-cp.stat().st_mtime < 21600:
        try:
            d=pd.read_csv(cp,parse_dates=["date"])
            if len(d)>=min_rows:
                return d.sort_values("date").tail(300)
        except Exception:
            pass

    last_err=None
    # download 방식과 Ticker.history 두 경로를 모두 시도
    for mode in ("download","history"):
        try:
            if mode=="download":
                d=yf.download(ys, period="18mo", interval="1d",
                              auto_adjust=False, progress=False, threads=False)
                if isinstance(d.columns,pd.MultiIndex):
                    d.columns=[c[0] if isinstance(c,tuple) else c for c in d.columns]
                d=d.reset_index()
            else:
                d=yf.Ticker(ys).history(period="18mo", interval="1d", auto_adjust=False)
                d=d.reset_index()

            ren={}
            for c in d.columns:
                lc=str(c).lower()
                if lc in ("date","datetime"): ren[c]="date"
                elif lc=="high": ren[c]="high"
                elif lc=="low": ren[c]="low"
                elif lc=="close": ren[c]="close"
                elif lc=="volume": ren[c]="volume"
            d=d.rename(columns=ren)
            need=["date","high","low","close","volume"]
            if not all(x in d.columns for x in need):
                raise RuntimeError(f"필수 컬럼 부족: {list(d.columns)}")
            d=d[need].copy()
            d["date"]=pd.to_datetime(d["date"],errors="coerce")
            try:
                d["date"]=d["date"].dt.tz_localize(None)
            except Exception:
                pass
            for c in ["high","low","close","volume"]:
                d[c]=pd.to_numeric(d[c],errors="coerce")
            d=d.dropna().drop_duplicates("date").sort_values("date").tail(300)
            if len(d)>=min_rows:
                d.to_csv(cp,index=False)
                return d
            raise RuntimeError(f"일봉 {len(d)}개 < {min_rows}개")
        except Exception as e:
            last_err=e

    raise RuntimeError(f"{ys} Yahoo 일봉 조회 실패: {last_err}")

def yf_price(symb, d=None):
    """현재가. fast_info 실패 시 최신 일봉 종가 사용."""
    ys=yf_symbol(symb)
    try:
        fi=yf.Ticker(ys).fast_info
        for key in ("last_price","previous_close"):
            try:
                v=fi.get(key)
            except Exception:
                v=getattr(fi,key,None)
            if v:
                return float(v)
    except Exception:
        pass
    if d is not None and len(d):
        return float(d.iloc[-1]["close"])
    raise RuntimeError(f"{ys} 현재가 조회 실패")

def yf_info_safe(symb):
    """재무정보는 실패해도 정밀분석 전체를 중단하지 않도록 빈 dict 반환."""
    ys=yf_symbol(symb)
    try:
        x=yf.Ticker(ys).info
        return x if isinstance(x,dict) else {}
    except Exception:
        return {}

class KISUS:
    def __init__(self,s):
        self.s=s; self.h=requests.Session(); self.last=0

    def req(self,m,u,label="",**kw):
        for n in range(5):
            wait=.75-(time.monotonic()-self.last)
            if wait>0: time.sleep(wait)
            r=self.h.request(m,u,**kw); self.last=time.monotonic()
            if "EGW00201" in r.text:
                time.sleep(1.5*(n+1)); continue
            if r.status_code>=400:
                raise RuntimeError(f"{label}: HTTP {r.status_code} {r.text[:180]}")
            x=r.json()
            if str(x.get("rt_cd","0")) not in ("0",""):
                raise RuntimeError(f"{label}: {x.get('msg1',x)}")
            return x
        raise RuntimeError(label+": KIS 호출 제한")

    def token(self):
        if TOKEN.exists():
            try:
                x=json.loads(TOKEN.read_text())
                if x.get("env")==self.s["env"] and time.time()<x["exp"]-120:
                    return x["t"]
            except: pass
        x=self.req("POST",self.s["base"]+"/oauth2/tokenP",label="토큰",
            json={"grant_type":"client_credentials","appkey":self.s["key"],"appsecret":self.s["secret"]},
            timeout=15)
        TOKEN.write_text(json.dumps({"env":self.s["env"],"t":x["access_token"],
            "exp":time.time()+int(x.get("expires_in",86400))}))
        return x["access_token"]

    def hd(self,tr):
        return {"authorization":"Bearer "+self.token(),"appkey":self.s["key"],
                "appsecret":self.s["secret"],"tr_id":tr,"custtype":"P"}

    def rank_call(self,path,trid,params,label):
        x=self.req("GET",self.s["base"]+path,label=label,
            headers=self.hd(trid),params=params,timeout=20)
        return x.get("output2",[]) or []

    def market_cap(self,excd):
        return self.rank_call("/uapi/overseas-stock/v1/ranking/market-cap","HHDFS76350100",
            {"EXCD":excd,"VOL_RANG":"3","KEYB":"","AUTH":""},f"{excd} 시가총액")

    def trade_value(self,excd):
        return self.rank_call("/uapi/overseas-stock/v1/ranking/trade-pbmn","HHDFS76320010",
            {"EXCD":excd,"NDAY":"0","VOL_RANG":"3","AUTH":"","KEYB":"","PRC1":"3","PRC2":""},
            f"{excd} 거래대금")

    def trade_growth(self,excd):
        return self.rank_call("/uapi/overseas-stock/v1/ranking/trade-growth","HHDFS76330000",
            {"EXCD":excd,"NDAY":"3","VOL_RANG":"3","AUTH":"","KEYB":""},f"{excd} 거래증가")

    def new_high(self,excd):
        return self.rank_call("/uapi/overseas-stock/v1/ranking/new-highlow","HHDFS76300000",
            {"EXCD":excd,"MINX":"4","VOL_RANG":"3","GUBN":"1","GUBN2":"1","KEYB":"","AUTH":""},
            f"{excd} 신고가")

    def price_detail(self,excd,symb):
        """
        해외주식 현재체결가(v1_해외주식-009)를 1순위로 사용합니다.
        /price 는 실전/모의 모두 사용 가능하고, /price-detail 은 실전 전용이라
        VTS 환경에서 전체 정밀분석이 실패하는 문제를 피합니다.
        """
        try:
            x=self.req("GET",self.s["base"]+"/uapi/overseas-price/v1/quotations/price",
                label=symb+" 현재가",headers=self.hd("HHDFS00000300"),
                params={"AUTH":"","EXCD":excd,"SYMB":symb},timeout=15)
            out=x.get("output",{}) or {}
            if out:
                return out
        except Exception:
            pass

        # 실전 환경이면 상세현재가도 보조적으로 시도
        if self.s.get("env")=="real":
            try:
                x=self.req("GET",self.s["base"]+"/uapi/overseas-price/v1/quotations/price-detail",
                    label=symb+" 현재가상세",headers=self.hd("HHDFS76200200"),
                    params={"AUTH":"","EXCD":excd,"SYMB":symb},timeout=15)
                out=x.get("output",{}) or {}
                if out:
                    return out
            except Exception:
                pass

        # 마지막 안전장치: yfinance
        try:
            fi=yf.Ticker(symb).fast_info
            last=fi.get("last_price") or fi.get("previous_close")
            if last:
                return {"last":str(last),"source":"yfinance"}
        except Exception:
            pass
        raise RuntimeError(f"{symb} 현재가 조회 실패")

    def daily(self,excd,symb):
        """
        KIS 해외주식 기간별시세(v1_해외주식-010)는 호출당 데이터 수가 제한되므로
        BYMD를 뒤로 이동하며 여러 번 이어 붙여 220거래일을 확보합니다.
        KIS가 일시 실패해도 yfinance 1년 일봉으로 정밀분석을 계속합니다.
        """
        cp=CACHE/f"US_{excd}_{symb}.csv"
        if cp.exists() and time.time()-cp.stat().st_mtime<21600:
            try:
                cached=pd.read_csv(cp,parse_dates=["date"])
                if len(cached)>=120:
                    return cached.sort_values("date").tail(260)
            except Exception:
                pass

        all_rows=[]
        bymd=""
        last_oldest=None
        kis_error=None

        try:
            for page in range(4):
                x=self.req("GET",self.s["base"]+"/uapi/overseas-price/v1/quotations/dailyprice",
                    label=f"{symb} 일봉({page+1})",headers=self.hd("HHDFS76240000"),
                    params={"AUTH":"","EXCD":excd,"SYMB":symb,"GUBN":"0",
                            "BYMD":bymd,"MODP":"1"},timeout=20)
                rows=x.get("output2",[]) or []
                if not rows:
                    break
                all_rows.extend(rows)

                # 응답의 가장 오래된 날짜를 다음 조회 기준일로 사용
                dates=[]
                for r in rows:
                    v=r.get("xymd") or r.get("stck_bsop_date") or r.get("date")
                    if v:
                        dates.append(str(v).replace("-",""))
                if not dates:
                    break
                oldest=min(dates)
                if oldest==last_oldest:
                    break
                last_oldest=oldest
                try:
                    bymd=(datetime.strptime(oldest,"%Y%m%d")-timedelta(days=1)).strftime("%Y%m%d")
                except Exception:
                    break
                if len(all_rows)>=240:
                    break
        except Exception as e:
            kis_error=e

        if all_rows:
            d=pd.DataFrame(all_rows)

            def col(keys):
                for key in keys:
                    if key in d.columns:
                        return key
                return None

            dc=col(["xymd","stck_bsop_date","date"])
            hc=col(["high","ovrs_hgpr","stck_hgpr"])
            lc=col(["low","ovrs_lwpr","stck_lwpr"])
            cc=col(["clos","last","ovrs_nmix_prpr","stck_clpr"])
            vc=col(["tvol","acml_vol","volume"])

            if all([dc,hc,lc,cc,vc]):
                d=d.rename(columns={dc:"date",hc:"high",lc:"low",cc:"close",vc:"volume"})
                d=d[["date","high","low","close","volume"]]
                d["date"]=pd.to_datetime(d["date"],errors="coerce")
                for key in ["high","low","close","volume"]:
                    d[key]=pd.to_numeric(d[key].astype(str).str.replace(",","",regex=False),errors="coerce")
                d=d.dropna().drop_duplicates("date").sort_values("date").tail(260)
                if len(d)>=120:
                    d.to_csv(cp,index=False)
                    return d

        # KIS 데이터가 120개 미만이거나 호출 실패 시 yfinance fallback
        try:
            y=yf.Ticker(symb).history(period="18mo",interval="1d",auto_adjust=False)
            if y is not None and len(y)>=120:
                y=y.reset_index()
                y=y.rename(columns={"Date":"date","High":"high","Low":"low","Close":"close","Volume":"volume"})
                y=y[["date","high","low","close","volume"]].copy()
                y["date"]=pd.to_datetime(y["date"],errors="coerce").dt.tz_localize(None)
                for key in ["high","low","close","volume"]:
                    y[key]=pd.to_numeric(y[key],errors="coerce")
                y=y.dropna().drop_duplicates("date").sort_values("date").tail(260)
                y.to_csv(cp,index=False)
                return y
        except Exception as ye:
            if kis_error is None:
                kis_error=ye

        raise RuntimeError(f"{symb} 일봉 데이터 120개 확보 실패: {kis_error}")
