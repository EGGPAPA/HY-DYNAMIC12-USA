import json
from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf


FILES=(Path("data/usa_candidates.json"),Path("data/usa_top12.json"))


def _universe():
    names={}
    for path in FILES:
        try:
            for row in json.loads(path.read_text(encoding="utf-8")):
                ticker=str(row.get("symbol") or row.get("티커") or "").strip().upper()
                if ticker:names[ticker]=str(row.get("name") or row.get("종목") or ticker)
        except Exception:pass
    return names


@st.cache_data(ttl=3600,show_spinner=False)
def _monthly(ticker):
    try:
        data=yf.download(ticker,period="10y",interval="1mo",auto_adjust=True,progress=False,threads=False)
        if isinstance(data.columns,pd.MultiIndex):data.columns=data.columns.get_level_values(0)
        return data.dropna(subset=["Close"])
    except Exception:return pd.DataFrame()


def _score(close,volume,i):
    if i<6:return None
    price=float(close.iloc[i]);mom3=(price/float(close.iloc[i-3])-1)*100;mom6=(price/float(close.iloc[i-6])-1)*100
    ma5=float(close.iloc[i-4:i+1].mean());prev_ma=float(close.iloc[i-5:i].mean());slope=(ma5/prev_ma-1)*100 if prev_ma else 0
    vr=1.0
    if volume is not None and len(volume)>i:
        base=pd.to_numeric(volume.iloc[i-5:i],errors="coerce").dropna()
        if len(base) and float(base.mean())>0:vr=float(volume.iloc[i])/float(base.mean())
    score=max(0,min(100,50+mom3*.8+mom6*.35+(10 if price>ma5 else -10)+(8 if slope>0 else -5)+max(-8,min(8,(vr-1)*12))))
    hits=int(mom3>0)+int(price>ma5 and slope>0)+int(vr>=1.0)
    return score,hits


def run_backtest(names,progress=None):
    events=[];items=list(names.items());thresholds=(65,70,75,80)
    for n,(ticker,name) in enumerate(items,1):
        data=_monthly(ticker)
        if len(data)>=20:
            close=pd.to_numeric(data["Close"],errors="coerce").dropna();volume=pd.to_numeric(data["Volume"],errors="coerce").reindex(close.index) if "Volume" in data else None;prev={t:False for t in thresholds}
            for i in range(6,len(close)-1):
                result=_score(close,volume,i)
                if not result:continue
                score,hits=result;entry=float(close.iloc[i]);future=close.iloc[i+1:min(i+13,len(close))];path=(future/entry-1)*100
                for threshold in thresholds:
                    on=score>=threshold and hits>=2
                    if on and not prev[threshold]:
                        row={"기준":threshold,"티커":ticker,"종목":name,"신호월":str(close.index[i])[:7],"점수":round(score,1),"12개월최고":float(path.max()) if len(path) else None,"12개월최대하락":float(path.min()) if len(path) else None}
                        for month in (3,6,12):row[f"{month}개월"]=(float(close.iloc[i+month])/entry-1)*100 if i+month<len(close) else None
                        events.append(row)
                    prev[threshold]=on
        if progress is not None:progress.progress(n/max(1,len(items)))
    return pd.DataFrame(events)


def _summary(events):
    rows=[]
    for threshold in (65,70,75,80):
        frame=events[events["기준"]==threshold] if not events.empty else pd.DataFrame();row={"진입기준":f"{threshold}점+ · 2/3 이상","신호수":len(frame)}
        for month in (3,6,12):
            series=pd.to_numeric(frame[f"{month}개월"],errors="coerce").dropna() if not frame.empty else pd.Series(dtype=float);row[f"{month}개월승률"]=(series.gt(0).mean()*100) if len(series) else None;row[f"{month}개월평균"]=series.mean() if len(series) else None
        annual=pd.to_numeric(frame["12개월"],errors="coerce").dropna() if not frame.empty else pd.Series(dtype=float);clean=annual[annual.lt(500)]
        row["12개월중앙값"]=annual.median() if len(annual) else None;row["12개월최악"]=annual.min() if len(annual) else None;row["12개월최고수익"]=annual.max() if len(annual) else None;row["손실확률"]=(annual.lt(0).mean()*100) if len(annual) else None;row["500%이상치수"]=int(annual.ge(500).sum()) if len(annual) else 0;row["500%제외평균"]=clean.mean() if len(clean) else None
        if len(annual):lo,hi=annual.quantile(.01),annual.quantile(.99);row["상하위1%제한평균"]=annual.clip(lo,hi).mean()
        else:row["상하위1%제한평균"]=None
        maximum=pd.to_numeric(frame["12개월최고"],errors="coerce").dropna() if not frame.empty else pd.Series(dtype=float);drawdown=pd.to_numeric(frame["12개월최대하락"],errors="coerce").dropna() if not frame.empty else pd.Series(dtype=float)
        for target in (10,20,30):row[f"+{target}%도달률"]=(maximum.ge(target).mean()*100) if len(maximum) else None
        row["평균MDD"]=drawdown.mean() if len(drawdown) else None;rows.append(row)
    return pd.DataFrame(rows)


def render_usa_backtest_tab():
    st.subheader("📈 USA 통합점수 전략검증")
    st.caption("저장된 미국시장 후보를 최근 10년 월봉으로 검증합니다. 미래정보를 쓰지 않으며 평균보다 중앙값·손실확률·이상치 보정값을 우선 확인하세요.")
    names=_universe();st.info(f"현재 검증 대상 {len(names)}개 · 미국시장 후보/TOP12")
    if st.button("▶ 65·70·75·80점 백테스트 실행",type="primary",use_container_width=True,key="usa_integrated_bt"):
        bar=st.progress(0);events=run_backtest(names,bar);bar.empty();st.session_state["usa_bt_events"]=events.to_dict("records")
    events=pd.DataFrame(st.session_state.get("usa_bt_events",[]))
    if events.empty:st.info("정밀 전체 업데이트 후 백테스트를 실행하세요.");return
    summary=_summary(events);display=summary.copy()
    pct_cols=[c for c in display.columns if "승률" in c or "확률" in c or "도달률" in c]
    return_cols=[c for c in display.columns if c.endswith("평균") or c in ("12개월중앙값","12개월최악","12개월최고수익","평균MDD")]
    for col in pct_cols:display[col]=display[col].map(lambda x:f"{x:.1f}%" if pd.notna(x) else "-")
    for col in return_cols:display[col]=display[col].map(lambda x:f"{x:+.2f}%" if pd.notna(x) else "-")
    st.dataframe(display,use_container_width=True,hide_index=True)
    if int(pd.to_numeric(summary["500%이상치수"],errors="coerce").fillna(0).max()):st.warning("+500% 이상 사례가 있습니다. 원본 평균보다 중앙값·500% 제외 평균·상하위 1% 제한 평균을 우선 보세요.")
    with st.expander("과거 신호 상세"):st.dataframe(events.sort_values(["기준","신호월"],ascending=[True,False]).head(500),use_container_width=True,hide_index=True)

