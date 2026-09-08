import json
from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf

CAND_FILE=Path("data/usa_candidates.json")
TOP12_FILE=Path("data/usa_top12.json")

def _load_rows():
    rows=[]
    for path in (CAND_FILE,TOP12_FILE):
        try:
            if path.exists():rows.extend(json.loads(path.read_text(encoding="utf-8")))
        except Exception:pass
    result=[];seen=set()
    for row in rows:
        ticker=str(row.get("symbol") or row.get("티커") or row.get("ticker") or "").strip().upper()
        if not ticker or ticker in seen:continue
        seen.add(ticker);result.append({"ticker":ticker,"name":row.get("name") or row.get("종목") or ticker,"exchange":row.get("exchange") or row.get("거래소") or ""})
    return result

@st.cache_data(ttl=600,show_spinner=False)
def _history(ticker):
    try:
        frame=yf.Ticker(ticker).history(period="1y",interval="1d",auto_adjust=False)
        return frame.dropna(subset=["Close"]) if frame is not None else pd.DataFrame()
    except Exception:return pd.DataFrame()

def _timing(row):
    history=_history(row["ticker"])
    if len(history)<65:return None
    close=pd.to_numeric(history["Close"],errors="coerce").dropna();volume=pd.to_numeric(history.get("Volume"),errors="coerce").reindex(close.index)
    ma20=close.rolling(20).mean();ma60=close.rolling(60).mean();ma120=close.rolling(120).mean()
    price=float(close.iloc[-1]);m20=float(ma20.iloc[-1]);m60=float(ma60.iloc[-1]);prior_high=float(close.iloc[-21:-1].max());previous=float(close.iloc[-2])
    gap20=(price/m20-1)*100 if m20 else 0;ret10=(price/float(close.iloc[-11])-1)*100;ret20=(price/float(close.iloc[-21])-1)*100
    rising20=m20>float(ma20.iloc[-6]);recent_cross=bool(((ma20>ma60)&(ma20.shift(1)<=ma60.shift(1))).tail(10).fillna(False).any());breakout=price>=prior_high and previous<prior_high
    base_volume=volume.iloc[-21:-1].dropna();recent_volume=volume.tail(3).dropna();volume_ratio=float(recent_volume.max()/base_volume.mean()) if len(base_volume) and base_volume.mean()>0 and len(recent_volume) else 1.0
    score=(20 if price>m20 else 0)+(15 if rising20 else 0)+(15 if price>m60 else 0)+(15 if recent_cross else 0)+(20 if breakout else (8 if price>=prior_high*.98 else 0))+(15 if volume_ratio>=1.5 else (8 if volume_ratio>=1.1 else 0))
    late=gap20>15 or ret20>35 or ret10>25
    if gap20>12:score-=20
    if ret10>25:score-=15
    score=max(0,min(100,round(score,1)))
    if late:label,action="🔴 급등·추격금지","신규매수 금지 · 20일선 눌림 대기"
    elif score>=75 and gap20<=8:label,action="🟢 상승초입","1차 분할매수 검토"
    elif score>=60:label,action="🟡 돌파확인","종가 돌파와 거래량 유지 확인"
    elif price>m60 and rising20:label,action="🔵 준비구간","직전 20일 고점 돌파 대기"
    else:label,action="⚪ 신호대기","관찰만 유지"
    first=max(m20,prior_high*.99)
    if label.startswith("🟢"):first=min(price,max(m20,prior_high*.995))
    second=m20*1.01;low10=float(close.tail(10).min());stop=min(price*.97,max(m20*.96,low10*.98))
    if label.startswith("🟢") and price>stop and first*.98<=price<=first*1.02:label,action="🟣 1차매수구간","1차 분할매수 가능"
    return {"ticker":row["ticker"],"name":row["name"],"exchange":row["exchange"],"label":label,"action":action,"score":score,"price":price,"buy1":first,"buy2":second,"stop":stop,"breakout":prior_high,"volume_ratio":round(volume_ratio,2),"gap20":round(gap20,1),"chart":pd.DataFrame({"종가":close,"20일선":ma20,"60일선":ma60,"120일선":ma120}).tail(120)}

def _priority(x):
    label=x["label"]
    return 0 if "1차매수구간" in label else 1 if "상승초입" in label else 2 if "돌파확인" in label else 3 if "준비구간" in label else 4

def _distance(x):return abs(x["price"]/x["buy1"]-1)*100 if x["buy1"] else 999

def _final_timing(x):
    label=x["label"];gap=(x["price"]/x["buy1"]-1)*100 if x["buy1"] else 999;dist=abs(gap);vol=x["volume_ratio"];score=x["score"]
    if "1차매수구간" in label:
        if dist<=1.5 and vol>=1 and score>=80:return "🟢 지금 1차 분할매수"
        return "🟡 매수가 근접 · 분할대기" if dist<=3 else "🟠 1차가 접근 대기"
    if "상승초입" in label:
        if dist<=1.5 and vol>=1.2 and score>=85:return "🟢 1차 분할매수 가능"
        return "🟡 눌림목 도달 대기" if gap>3 else "🔵 지지 확인 후 매수"
    if "돌파확인" in label:return "🟡 돌파 지지 확인 후 소량" if 0<=gap<=3 and vol>=1.5 and score>=80 else "🔴 추격금지 · 눌림대기"
    return "⚪ 관찰 · 아직 매수 아님"

def render_usa_rise_timing_tab():
    st.subheader("📍 미국주식 상승시점 관찰");st.caption("한국판과 같은 기술적 기준으로 NASDAQ·NYSE·AMEX 저장 후보를 분석합니다. TOP12 통합판정과는 별도 관찰 신호입니다.")
    rows=_load_rows()
    if not rows:st.warning("분석 대상이 없습니다. 먼저 ‘전체시장 분석’에서 미국시장 후보를 생성하세요.");return
    st.info(f"현재 대상 {len(rows):,}개 · 저장된 미국시장 후보 + TOP12")
    if st.button("🔎 미국주식 상승시점 분석",type="primary",use_container_width=True):
        results=[];bar=st.progress(0);status=st.empty()
        for i,row in enumerate(rows):
            status.info(f"{i+1}/{len(rows)} · {row['ticker']} 분석");result=_timing(row)
            if result:results.append(result)
            bar.progress((i+1)/len(rows))
        st.session_state["usa_rise_results"]=results;status.success(f"분석 완료 · {len(results)}종목");bar.empty()
    results=st.session_state.get("usa_rise_results",[])
    if not results:return
    results=sorted(results,key=lambda x:(_priority(x),_distance(x),-x["volume_ratio"],-x["score"]))
    buy=[x for x in results if "1차매수구간" in x["label"]];early=[x for x in results if "상승초입" in x["label"]];brk=[x for x in results if "돌파확인" in x["label"]];ready=[x for x in results if "준비구간" in x["label"]]
    a,b,c,d=st.columns(4);a.metric("🟣 1차매수구간",len(buy));b.metric("🟢 상승초입",len(early));c.metric("🟡 돌파확인",len(brk));d.metric("🔵 준비구간",len(ready))
    st.info("종합 매수 타이밍은 **단계 → 현재가와 1차 매수가 거리 → 거래량 → 시점점수**를 합쳐 판정합니다.")
    view=pd.DataFrame([{"우선순위":n,"종합 매수 타이밍":_final_timing(x),"종목":x["name"],"티커":x["ticker"],"거래소":x["exchange"],"단계":x["label"],"현재가($)":f"${x['price']:,.2f}","1차가 거리":f"{(x['price']/x['buy1']-1)*100:+.1f}%","거래량 배수":x["volume_ratio"],"시점점수":x["score"],"1차 매수($)":f"${x['buy1']:,.2f}","2차 눌림($)":f"${x['buy2']:,.2f}","손절 참고($)":f"${x['stop']:,.2f}","돌파 기준($)":f"${x['breakout']:,.2f}","행동":x["action"]} for n,x in enumerate(results,1)])
    st.dataframe(view,use_container_width=True,hide_index=True,column_config={"우선순위":st.column_config.NumberColumn(format="%d위"),"거래량 배수":st.column_config.NumberColumn(format="%.2f배"),"시점점수":st.column_config.NumberColumn(format="%.0f점")})
    labels=[f"{x['name']} ({x['ticker']})" for x in results];selected=st.selectbox("상세 종목",labels,key="usa_rise_detail");item=results[labels.index(selected)]
    q1,q2,q3,q4=st.columns(4);q1.metric("종합 매수 타이밍",_final_timing(item));q2.metric("현재 단계",item["label"]);q3.metric("시점점수",f"{item['score']:.0f}점");q4.metric("1차 매수 참고",f"${item['buy1']:,.2f}")
    st.info(f"행동: **{item['action']}** · 현재가 ${item['price']:,.2f} · 거래량 {item['volume_ratio']:.2f}배 · 손절 참고 ${item['stop']:,.2f}");st.line_chart(item["chart"],height=360)
    st.caption("기술적 관찰 신호이며 매수 보장은 아닙니다. 실제 주문 전 실적·공시·시장 상황을 함께 확인하세요.")

