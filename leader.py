
def leader_metrics(d):
    if d is None or len(d)<120:
        return {"leader_score":0,"rs20":0,"rs60":0,"near_high":0,"notes":["데이터 부족"]}
    x=d.copy().sort_values("date"); p=float(x.iloc[-1].close)
    r20=p/float(x.iloc[-21].close)-1; r60=p/float(x.iloc[-61].close)-1
    high120=float(x.tail(120).high.max()); near=p/high120 if high120 else 0
    val=x.close*x.volume
    vr=float(val.iloc[-1]/val.tail(20).mean()) if val.tail(20).mean() else 0
    ma20=float(x.close.tail(20).mean()); ma50=float(x.close.tail(50).mean())
    mom20=max(0,min(100,(r20+0.08)/0.33*100))
    mom60=max(0,min(100,(r60+0.12)/0.62*100))
    momentum=mom20*.45+mom60*.55
    highscore=max(0,min(100,(near-.72)/.28*100))
    valscore=max(0,min(100,vr/2*100))
    trend=(50 if p>ma20 else 0)+(50 if ma20>ma50 else 0)
    score=round(momentum*.35+highscore*.25+valscore*.20+trend*.20,1)
    notes=[]
    if r20>.10:notes.append("20일 강한 상승")
    if r60>.20:notes.append("60일 주도 모멘텀")
    if near>=.95:notes.append("120일 신고가 근접")
    if vr>=1.3:notes.append("거래대금 증가")
    if p>ma20>ma50:notes.append("정배열")
    return {"leader_score":score,"rs20":round(r20*100,1),"rs60":round(r60*100,1),
            "near_high":round(near*100,1),"notes":notes}
