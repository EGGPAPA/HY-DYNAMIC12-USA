
import pandas as pd

def analyze(d):
    if d is None or len(d)<60:
        return {"score":None,"signal":"계산불가","reasons":["일봉 60개 미만"]}
    x=d.copy().sort_values("date")
    pc=x.close.shift(1)
    x["tr"]=pd.concat([x.high-x.low,(x.high-pc).abs(),(x.low-pc).abs()],axis=1).max(axis=1)
    x["atr"]=x.tr.rolling(14).mean()
    for n in [20,50,200]:
        x[f"ma{n}"]=x.close.rolling(n).mean()
    x["value"]=x.close*x.volume
    x["value20"]=x.value.rolling(20).mean()
    a=x.iloc[-1]; p=float(a.close); atr=float(a.atr)
    score=0; reasons=[]

    if p>a.ma20: score+=10; reasons.append("20일선 위")
    if p>a.ma50: score+=10; reasons.append("50일선 위")
    if a.ma20>a.ma50: score+=10; reasons.append("20>50 정배열")
    if len(x)>=200 and pd.notna(a.ma200) and p>a.ma200: score+=8; reasons.append("200일선 위")

    r20=p/float(x.iloc[-21].close)-1
    r60=p/float(x.iloc[-61].close)-1
    if r20>0: score+=8
    if r60>0.10: score+=8; reasons.append(f"60일 모멘텀 {r60:+.1%}")

    vr=float(a.value/a.value20) if pd.notna(a.value20) and a.value20 else 0
    if vr>=2: score+=18; reasons.append(f"거래대금 {vr:.1f}배")
    elif vr>=1.3: score+=12
    elif vr>=.9: score+=6

    gap20=(p/float(a.ma20)-1)*100 if a.ma20 else 99
    if gap20<=3: score+=16
    elif gap20<=7: score+=10
    elif gap20<=12: score+=4
    else: reasons.append("20일선 과이격")

    score=max(0,min(100,int(score)))
    entry=min(float(a.ma20),p-.35*atr)
    entry2=entry-.8*atr
    stop=max(entry-1.5*atr,entry*.93)
    gap=(p/entry-1)*100 if entry else 999

    if score>=86 and gap<=3: signal="1차매수"
    elif score>=80 and gap<=6: signal="소액진입"
    elif score>=70: signal="눌림목 대기"
    elif score>=60: signal="관찰"
    else: signal="현금대기"

    return {"score":score,"signal":signal,"entry":round(entry,2),"entry2":round(entry2,2),
        "target":round(entry*1.15,2),"stop":round(stop,2),"atr_pct":round(atr/p*100,2),
        "gap":round(gap,2),"value_ratio":round(vr,2),"reasons":reasons}
