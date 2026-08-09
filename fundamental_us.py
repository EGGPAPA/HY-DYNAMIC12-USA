
def _clip(x,a=0,b=100): return max(a,min(b,x))
def _n(v):
    try:return float(v)
    except:return None

def score_yf(info):
    """yfinance 정보가 있을 때만 재무/밸류 점수화. 없으면 중립 50점."""
    if not info:
        return {"fund_score":50.0,"profitability":50.0,"growth":50.0,"quality":50.0,
                "roe":None,"profit_margin":None,"revenue_growth":None,"debt_equity":None,
                "forward_pe":None,"status":"재무데이터 없음"}
    roe=_n(info.get("returnOnEquity"))
    pm=_n(info.get("profitMargins"))
    rg=_n(info.get("revenueGrowth"))
    eg=_n(info.get("earningsGrowth"))
    de=_n(info.get("debtToEquity"))
    fpe=_n(info.get("forwardPE"))

    def higher(v,bad,good):
        if v is None:return 50
        return _clip((v-bad)/(good-bad)*100)
    def lower(v,good,bad):
        if v is None:return 50
        return _clip((bad-v)/(bad-good)*100)

    prof=higher((roe*100 if roe is not None else None),0,25)*.55 + higher((pm*100 if pm is not None else None),0,20)*.45
    vals=[x for x in [rg,eg] if x is not None]
    growth=sum(higher(x*100,-10,30) for x in vals)/len(vals) if vals else 50
    quality=lower(de,50,250)*.65 + lower(fpe,15,45)*.35
    score=round(prof*.40+growth*.35+quality*.25,1)
    status="재무 우수" if score>=70 else "재무 양호" if score>=58 else "재무 중립" if score>=42 else "재무 주의"
    return {"fund_score":score,"profitability":round(prof,1),"growth":round(growth,1),
            "quality":round(quality,1),"roe":None if roe is None else round(roe*100,1),
            "profit_margin":None if pm is None else round(pm*100,1),
            "revenue_growth":None if rg is None else round(rg*100,1),
            "debt_equity":de,"forward_pe":fpe,"status":status}
