
import pandas as pd

def _num(v):
    try:return float(str(v).replace(",","").replace("%","").strip() or 0)
    except:return 0.0
def _pick(r,keys,default=""):
    for k in keys:
        if k in r and str(r.get(k,"")).strip() not in ("","None"):
            return r.get(k)
    return default

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
        rows=[]; errors=[]
        for excd in ["NAS","NYS","AMS"]:
            for source,fn in [("거래대금",self.api.trade_value),("시가총액",self.api.market_cap),
                              ("거래증가",self.api.trade_growth),("신고가",self.api.new_high)]:
                try: rows+=self.normalize(fn(excd),excd,source,per_source)
                except Exception as e: errors.append(f"{excd} {source}: {e}")
        if not rows:
            raise RuntimeError("미국시장 순위 데이터를 만들지 못했습니다. "+" | ".join(errors[:4]))
        df=pd.DataFrame(rows)
        result=[]
        weights={"거래대금":1.0,"거래증가":.9,"신고가":.9,"시가총액":.55}
        for (sym,excd),g in df.groupby(["symbol","exchange"],sort=False):
            score=sum(max(0,101-r.source_rank*3)*weights.get(r.source,.5) for _,r in g.iterrows())
            src=set(g.source); score=min(100,score/2+max(0,len(src)-1)*15)
            result.append({"symbol":sym,"name":g.iloc[0].name if False else g.iloc[0]["name"],
                           "exchange":excd,"sources":"/".join(sorted(src)),
                           "source_count":len(src),"pre_score":round(score,1)})
        x=pd.DataFrame(result).sort_values(["pre_score","source_count"],ascending=False)
        return x.head(int(candidate_n)).reset_index(drop=True),errors
