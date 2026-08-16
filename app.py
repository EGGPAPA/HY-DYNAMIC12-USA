
import streamlit as st
import pandas as pd
from config import settings,save
from kis_us import KISUS, yf_daily, yf_price, yf_info_safe
from rank_us import USScanner
from engine import analyze
from leader import leader_metrics
from fundamental_us import score_yf

from pathlib import Path
import json
import html

STATE_DIR=Path("data")
STATE_DIR.mkdir(exist_ok=True)
TOP12_FILE=STATE_DIR/"usa_top12.json"
CAND_FILE=STATE_DIR/"usa_candidates.json"

def save_json(path,obj):
    try:
        path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    except Exception:
        pass

def load_json(path,default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def usa_exit_plan(entry, current):
    """
    USA V1.6 수익관리
    - +15%: 30~50% 분할매도/원금 일부 회수
    - +20%: 추가 25% 분할매도
    - +25%: 추가 25% 분할매도
    - 나머지: 추세 유지 시 보유
    """
    try:
        entry=float(entry); current=float(current)
        if entry <= 0:
            return {"return_pct":0.0,"stage":"대기","action":"진입 전"}
        r=(current/entry-1)*100
        if r >= 25:
            return {"return_pct":round(r,1),"stage":"+25% 이상","action":"추가 25% 분할매도 · 잔여분 추세보유"}
        if r >= 20:
            return {"return_pct":round(r,1),"stage":"+20% 이상","action":"추가 25% 분할매도"}
        if r >= 15:
            return {"return_pct":round(r,1),"stage":"+15% 도달","action":"30~50% 분할매도 · 원금 일부 회수"}
        if r >= 10:
            return {"return_pct":round(r,1),"stage":"+10% 이상","action":"매도보다 추세 확인 · 보유 우선"}
        return {"return_pct":round(r,1),"stage":"진행중","action":"계획 유지"}
    except Exception:
        return {"return_pct":0.0,"stage":"계산불가","action":"확인 필요"}


st.set_page_config(page_title="HY DYNAMIC12 USA V2.2 BLINK",page_icon="🇺🇸",layout="wide")

st.markdown("""
<style>
/* HY MOBILE V2.0 */

/* V2.2 적극매수 종목명 점멸 */
@keyframes hyActiveBlink {
  0%, 100% { opacity: 1; text-shadow: 0 0 8px rgba(67, 255, 135, .80); }
  50% { opacity: .30; text-shadow: 0 0 2px rgba(67, 255, 135, .18); }
}
@keyframes hyActivePulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: .35; transform: scale(.90); }
}
.hy-usa-table-wrap {
  width: 100%;
  overflow-x: auto;
  border: 1px solid rgba(128,128,128,.22);
  border-radius: 10px;
  margin-top: .5rem;
}
.hy-usa-table {
  width: 100%;
  min-width: 1180px;
  border-collapse: collapse;
  color: #f5f7fa;
  background: rgba(10,14,20,.35);
  font-size: .88rem;
}
.hy-usa-table th {
  background: rgba(36,41,50,.95);
  color: #d9dee7;
  padding: 9px 8px;
  border-bottom: 1px solid rgba(128,128,128,.25);
  text-align: right;
  white-space: nowrap;
}
.hy-usa-table th:nth-child(1),
.hy-usa-table th:nth-child(2),
.hy-usa-table th:nth-child(3),
.hy-usa-table td:nth-child(1),
.hy-usa-table td:nth-child(2),
.hy-usa-table td:nth-child(3) {
  text-align: left;
}
.hy-usa-table td {
  padding: 9px 8px;
  border-bottom: 1px solid rgba(128,128,128,.16);
  text-align: right;
  white-space: nowrap;
}
.hy-active-dot {
  display: inline-block;
  color: #43ff87;
  margin-right: 6px;
  animation: hyActivePulse 1.35s ease-in-out infinite;
}
.hy-active-name {
  display: inline-block;
  color: #8cffae;
  font-weight: 800;
  animation: hyActiveBlink 1.35s ease-in-out infinite;
}
.hy-normal-name {
  color: #f5f7fa;
  font-weight: 650;
}
.hy-scorebar {
  display:inline-flex;
  align-items:center;
  gap:7px;
  min-width:115px;
}
.hy-scoretrack {
  display:inline-block;
  width:72px;
  height:8px;
  border-radius:99px;
  background:#303641;
  overflow:hidden;
}
.hy-scorefill {
  display:block;
  height:100%;
  background:#ff4b55;
  border-radius:99px;
}
.hy-judge {
  color:#f5f7fa;
  font-weight:700;
}
.hy-help {
  margin:.45rem 0 .6rem 0;
  color:#aeb6c2;
  font-size:.82rem;
}

.block-container {padding-top: 1rem; padding-bottom: 2rem; max-width: 1400px;}
div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.18); padding: .55rem .7rem; border-radius: 12px;}
div[data-testid="stDataFrame"] {font-size: 0.88rem;}
@media (max-width: 768px) {
  .block-container {padding-left: .55rem; padding-right: .55rem; padding-top: .55rem;}
  h1 {font-size: 1.55rem !important; line-height: 1.2;}
  h2, h3 {font-size: 1.15rem !important;}
  div[data-testid="stMetric"] {padding: .45rem .5rem; border-radius: 10px;}
  div[data-testid="stMetricValue"] {font-size: 1.15rem;}
  div[data-testid="stMetricLabel"] {font-size: .78rem;}
  .stButton button {min-height: 44px; font-size: 1rem; border-radius: 10px;}
  div[data-testid="stDataFrame"] {font-size: .78rem;}
  /* make tabs horizontally scrollable on iPhone */
  div[data-baseweb="tab-list"] {overflow-x: auto; white-space: nowrap;}
}
</style>
""", unsafe_allow_html=True)
st.title("HY DYNAMIC12 USA V2.2 · AUTO JUDGMENT")
st.caption("NASDAQ · NYSE · AMEX → 거래대금/시총/거래증가/신고가 → 주도주 정밀분석 → 오늘의 USA TOP12")
s=settings()


def render_usa_top12_blink(top):
    """적극매수 종목만 초록 점 + 종목명이 부드럽게 점멸하는 USA TOP12 핵심표."""
    if not top:
        return

    def esc(v):
        return html.escape(str(v))

    def money(v):
        try:
            return f"{float(v):,.2f}"
        except Exception:
            return "-"

    headers=[
        "순위","종목","티커","현재가($)","USA점수","판정점수",
        "판정","1차매수가($)","2차매수가($)","3%손절가($)"
    ]

    out=['<div class="hy-usa-table-wrap"><table class="hy-usa-table"><thead><tr>']
    out += [f"<th>{h}</th>" for h in headers]
    out.append("</tr></thead><tbody>")

    for r in top[:12]:
        raw_j=str(r.get("판정",""))
        active=raw_j.startswith("적극매수")
        name=esc(r.get("종목",""))
        ticker=esc(r.get("티커",""))
        if active:
            name_html=f'<span class="hy-active-dot">●</span><span class="hy-active-name">{name}</span>'
        else:
            name_html=f'<span class="hy-normal-name">{name}</span>'

        usa=float(r.get("USA점수",0) or 0)
        jscore=float(r.get("판정점수",usa) or 0)
        score_html=(
            f'<span class="hy-scorebar"><span class="hy-scoretrack">'
            f'<span class="hy-scorefill" style="width:{max(0,min(100,usa)):.1f}%"></span>'
            f'</span><b>{usa:.1f}</b></span>'
        )
        judge_html=(
            f'<span class="hy-scorebar"><span class="hy-scoretrack">'
            f'<span class="hy-scorefill" style="width:{max(0,min(100,jscore)):.1f}%"></span>'
            f'</span><b>{jscore:.1f}</b></span>'
        )

        if raw_j.startswith("적극매수"):
            badge="🟢 적극매수"
        elif raw_j.startswith("매수후보"):
            badge="🟡 매수후보"
        elif raw_j.startswith("관찰"):
            badge="🔵 관찰"
        elif raw_j.startswith("현금대기"):
            badge="⚪ 현금대기"
        else:
            badge=esc(raw_j)

        row=[
            esc(r.get("순위","")),
            name_html,
            ticker,
            money(r.get("현재가($)")),
            score_html,
            judge_html,
            f'<span class="hy-judge">{badge}</span>',
            money(r.get("1차매수가($)")),
            money(r.get("2차매수가($)")),
            money(r.get("3%손절가($)")),
        ]
        out.append("<tr>"+"".join(f"<td>{c}</td>" for c in row)+"</tr>")

    out.append("</tbody></table></div>")
    st.markdown("".join(out),unsafe_allow_html=True)
    st.markdown(
        '<div class="hy-help">🟢 적극매수 종목만 <b>초록 점 + 종목명</b>이 약 1.35초 주기로 부드럽게 점멸합니다. '
        '매수후보·관찰·현금대기는 정적으로 표시됩니다.</div>',
        unsafe_allow_html=True
    )


tabs=st.tabs(["오늘 TOP12","미국시장 스캔","상세","자금관리","KIS 설정","전략 규칙"])

with tabs[4]:
    st.subheader("KIS 설정")
    env=st.selectbox("환경",["real","demo"],index=0 if s["env"]=="real" else 1)
    k=st.text_input("새 App Key",type="password")
    sec=st.text_input("새 App Secret",type="password")
    ac=st.text_input("계좌 앞 8자리",value=s["account"],max_chars=8)
    pr=st.text_input("상품코드",value=s["product"],max_chars=2)
    if st.button("KIS 설정 저장"):
        save(k,sec,ac,pr,env); st.success("저장 완료"); st.rerun()

with tabs[1]:
    st.subheader("NASDAQ + NYSE + AMEX 주도주 스캔")
    c1,c2=st.columns(2)
    cand_n=c1.number_input("정밀분석 후보 수",20,70,40,5)
    per_source=c2.number_input("거래소별·랭킹별 수집 수",10,40,25,5)
    st.info("미국은 한국의 외국인·기관 일별 수급과 구조가 달라, 수급 대신 거래대금·거래증가·신고가·시총 순위를 결합합니다.")
    if st.button("① 미국시장 후보 생성",type="primary",use_container_width=True):
        if not s["key"] or not s["secret"]: st.error("KIS App Key/Secret을 먼저 저장하세요.")
        else:
            try:
                api=KISUS(s); scan=USScanner(api)
                cand,errs=scan.candidates(cand_n,per_source)
                st.session_state["us_candidates"]=cand; st.session_state["us_errors"]=errs
                save_json(CAND_FILE,cand.to_dict("records"))
                st.success(f"주도주 후보 {len(cand)}개 생성")
            except Exception as e: st.error(str(e))
    cand=st.session_state.get("us_candidates")
    if cand is None and CAND_FILE.exists():
        _saved=load_json(CAND_FILE,[])
        if _saved:
            cand=pd.DataFrame(_saved)
            st.session_state["us_candidates"]=cand
    if isinstance(cand,pd.DataFrame) and not cand.empty:
        st.dataframe(cand,use_container_width=True,hide_index=True,
            column_config={"pre_score":st.column_config.ProgressColumn("1차주도점수",min_value=0,max_value=100,format="%.1f")})
        if st.button("② 정밀분석 → USA TOP12",type="primary",use_container_width=True):
            import yfinance as yf
            api=KISUS(s); rows=[]; details={}
            bar=st.progress(0); msg=st.empty()
            recs=cand.to_dict("records")
            for i,r in enumerate(recs):
                sym=r["symbol"]; excd=r["exchange"]
                msg.info(f"{i+1}/{len(recs)} {sym} 분석")
                try:
                    # V1.5: 후보 선정은 KIS, 정밀분석은 Yahoo Finance로 분리
                    d=yf_daily(sym); a=analyze(d); lm=leader_metrics(d)
                    px=yf_price(sym,d)
                    pdeta={"last":px,"source":"yfinance"}
                    info=yf_info_safe(sym)
                    fn=score_yf(info)
                    final=round(lm["leader_score"]*.35+a["score"]*.25+r["pre_score"]*.15+
                                min(100,a["value_ratio"]*50)*.10+fn["fund_score"]*.15,1)

                    # 최종 자동판정: 100점 통합점수 기준
                    if final >= 85:
                        signal="적극매수"
                    elif final >= 75:
                        signal="매수후보"
                    elif final >= 65:
                        signal="관찰"
                    else:
                        signal="현금대기"

                    # 과이격 안전장치: 점수가 높아도 추격매수 금지
                    if lm["near_high"]>=98 and a["gap"]>6:
                        signal="관찰"
                    px=float(pdeta.get("last",pdeta.get("clos",d.iloc[-1].close)) or d.iloc[-1].close)
                    rows.append({"순위":0,"종목":r["name"],"티커":sym,"거래소":excd,
                        "포착경로":r["sources"],"현재가($)":round(px,2),"USA점수":final,
                        "주도주":lm["leader_score"],"기술":a["score"],"재무":fn["fund_score"],
                        "20일RS(%)":lm["rs20"],"60일RS(%)":lm["rs60"],"120일고점대비(%)":lm["near_high"],
                        "거래대금배수":a["value_ratio"],"재무판정":fn["status"],"ROE(%)":fn["roe"],
                        "매출성장(%)":fn["revenue_growth"],"Forward PER":fn["forward_pe"],
                        "판정":f"{signal} ({final:.1f}점)","판정점수":final,"1차매수가($)":a["entry"],"2차매수가($)":a["entry2"],
                        "+15%목표($)":a["target"],"ATR(%)":a["atr_pct"]})
                    details[sym]=(d,a,lm,fn,pdeta)
                except Exception as e:
                    errtxt=str(e)
                    rows.append({"순위":0,"종목":r["name"],"티커":sym,"거래소":excd,
                                 "USA점수":None,"판정":"조회오류","오류":errtxt[:300]})
                    st.session_state.setdefault("us_precision_errors",[]).append(f"{sym}: {errtxt}")
                bar.progress((i+1)/max(1,len(recs)))
            rows.sort(key=lambda x:x["USA점수"] if isinstance(x.get("USA점수"),(int,float)) else -1,reverse=True)
            for n,r in enumerate(rows,1):r["순위"]=n
            valid_rows=[x for x in rows if isinstance(x.get("USA점수"),(int,float))]
            st.session_state["us_ranked"]=valid_rows; st.session_state["us_details"]=details
            save_json(TOP12_FILE,valid_rows[:12])
            bar.empty();msg.success(f"USA TOP12 생성 완료 · 정상분석 {len(valid_rows)}개")

with tabs[0]:
    rows=st.session_state.get("us_ranked",[])
    if not rows:
        rows=load_json(TOP12_FILE,[])
        if rows:
            st.session_state["us_ranked"]=rows
    top=[r for r in rows if isinstance(r.get("USA점수"),(int,float))][:12]

    if not top:
        st.warning("저장된 TOP12가 없습니다.")

        _auto_err=st.session_state.get("usa_auto_error")
        if _auto_err:
            st.error("직전 자동 생성에서 오류가 발생했습니다.")
            st.code(_auto_err)

        _cand_saved=load_json(CAND_FILE,[])
        c1,c2,c3=st.columns(3)
        c1.metric("저장 후보수", len(_cand_saved))
        _saved_top=load_json(TOP12_FILE,[])
        _saved_valid=[x for x in _saved_top if isinstance(x.get("USA점수"),(int,float))]
        c2.metric("저장 TOP12수", min(12,len(_saved_valid)))
        c3.metric("KIS키 상태", "설정됨" if s.get("key") and s.get("secret") else "미설정")
        st.caption("V1.5 데이터 경로: KIS = 후보 40개 발굴 / Yahoo Finance = 일봉·현재가·재무 정밀분석")

        st.caption("처음 한 번은 아래 버튼으로 후보 생성과 정밀분석을 연속 실행하세요. 이후에는 결과가 저장되어 앱을 다시 열어도 TOP12가 바로 표시됩니다.")

        if st.button("🚀 오늘 USA TOP12 자동 생성", type="primary", use_container_width=True):
            if not s["key"] or not s["secret"]:
                st.error("KIS 설정에서 App Key / App Secret을 먼저 저장하세요.")
            else:
                import yfinance as yf
                try:
                    api=KISUS(s)
                    scan=USScanner(api)
                    cand,errs=scan.candidates(40,25)
                    st.session_state["us_candidates"]=cand
                    st.session_state["us_errors"]=errs
                    save_json(CAND_FILE,cand.to_dict("records"))
                    st.info(f"1차 후보 {len(cand)}개 생성 · 스캔오류 {len(errs)}개")

                    if cand is None or len(cand)==0:
                        raise RuntimeError("미국시장 1차 후보가 0개입니다. KIS 미국주식 API 설정 또는 거래소 코드 조회를 확인해야 합니다.")

                    result=[]; details={}
                    st.session_state["us_precision_errors"]=[]
                    bar=st.progress(0); msg=st.empty()
                    recs=cand.to_dict("records")
                    for i,r in enumerate(recs):
                        sym=r["symbol"]; excd=r["exchange"]
                        msg.info(f"{i+1}/{len(recs)} {sym} 분석")
                        try:
                            # V1.5 HYBRID: KIS는 후보발굴, Yahoo Finance는 일봉/현재가/재무
                            d=yf_daily(sym); a=analyze(d); lm=leader_metrics(d)
                            px=yf_price(sym,d)
                            pdeta={"last":px,"source":"yfinance"}
                            info=yf_info_safe(sym)
                            fn=score_yf(info)
                            final=round(lm["leader_score"]*.35+a["score"]*.25+r["pre_score"]*.15+
                                        min(100,a["value_ratio"]*50)*.10+fn["fund_score"]*.15,1)

                            if final >= 85:
                                signal="적극매수"
                            elif final >= 75:
                                signal="매수후보"
                            elif final >= 65:
                                signal="관찰"
                            else:
                                signal="현금대기"
                            if lm["near_high"]>=98 and a["gap"]>6:
                                signal="관찰"

                            px=float(pdeta.get("last",pdeta.get("clos",d.iloc[-1].close)) or d.iloc[-1].close)
                            result.append({"순위":0,"종목":r["name"],"티커":sym,"거래소":excd,
                                "포착경로":r["sources"],"현재가($)":round(px,2),"USA점수":final,
                                "주도주":lm["leader_score"],"기술":a["score"],"재무":fn["fund_score"],
                                "20일RS(%)":lm["rs20"],"60일RS(%)":lm["rs60"],"120일고점대비(%)":lm["near_high"],
                                "거래대금배수":a["value_ratio"],"재무판정":fn["status"],"ROE(%)":fn["roe"],
                                "매출성장(%)":fn["revenue_growth"],"Forward PER":fn["forward_pe"],
                                "판정":f"{signal} ({final:.1f}점)","판정점수":final,
                                "1차매수가($)":a["entry"],"2차매수가($)":a["entry2"],
                                "평균매수가($)":round((a["entry"]+a["entry2"])/2,2),"3%손절가($)":round(((a["entry"]+a["entry2"])/2)*0.97,2),
                                "+15%목표($)":a["target"],"+20%목표($)":round(a["entry"]*1.20,2),"+25%목표($)":round(a["entry"]*1.25,2),"ATR(%)":a["atr_pct"]})
                            details[sym]=(d,a,lm,fn,pdeta)
                        except Exception as e:
                            errtxt=str(e)
                            result.append({"순위":0,"종목":r["name"],"티커":sym,"거래소":excd,
                                           "USA점수":None,"판정":"조회오류","오류":errtxt[:300]})
                            st.session_state.setdefault("us_precision_errors",[]).append(f"{sym}: {errtxt}")
                        bar.progress((i+1)/max(1,len(recs)))

                    result.sort(key=lambda x:x["USA점수"] if isinstance(x.get("USA점수"),(int,float)) else -1,reverse=True)
                    for n,r in enumerate(result,1): r["순위"]=n

                    valid=[x for x in result if isinstance(x.get("USA점수"),(int,float))]
                    st.session_state["us_ranked"]=valid
                    st.session_state["us_details"]=details
                    save_json(TOP12_FILE,valid[:12])

                    bar.empty()
                    if valid:
                        msg.success(f"USA TOP12 생성 완료 · 정상분석 {len(valid)}개 / 전체 {len(result)}개")
                        st.session_state.pop("usa_auto_error",None)
                        st.rerun()
                    else:
                        msg.error("후보는 생성됐지만 정상 분석 종목이 0개입니다.")
                        _pe=st.session_state.get("us_precision_errors",[])
                        st.session_state["usa_auto_error"]="정밀분석 0개: Yahoo Finance 일봉/현재가 조회가 모두 실패했습니다."
                        st.error(st.session_state["usa_auto_error"])
                        if _pe:
                            with st.expander("정밀분석 실제 오류 보기", expanded=True):
                                for _e in _pe[:20]:
                                    st.code(_e)
                except Exception as e:
                    st.session_state["usa_auto_error"]=repr(e)
                    st.error("USA TOP12 자동 생성 실패")
                    st.exception(e)
    else:
        buys=[r for r in top if str(r["판정"]).startswith(("적극매수","매수후보"))]
        a,b,c,d=st.columns(4)
        a.metric("오늘 1위",top[0]["티커"]); b.metric("USA점수",top[0]["USA점수"])
        c.metric("진입후보",len(buys)); d.metric("운용원칙","최대 6종목")
        if buys: st.success("우선 진입후보: "+", ".join(x["티커"] for x in buys[:3]))
        if st.button("🔄 오늘 TOP12 다시 계산", use_container_width=True):
            if TOP12_FILE.exists(): TOP12_FILE.unlink()
            st.session_state.pop("us_ranked",None)
            st.rerun()
        else: st.warning("TOP12 안에도 적극매수/매수후보 없음 — 현금대기")

        st.markdown("### 🏆 USA TOP12 핵심표")
        render_usa_top12_blink(top)
        st.markdown("### 📱 아이폰 핵심 보기")
        _mobile_cols=[c for c in ["순위","티커","종목","현재가($)","판정점수","판정표시","1차매수가($)","2차매수가($)","3%손절가($)","+15%목표($)"] if c in pd.DataFrame(top).columns]
        _mobile_df=pd.DataFrame(top)[_mobile_cols].head(12)
        st.dataframe(_mobile_df,use_container_width=True,hide_index=True,height=460)
        _top_df=pd.DataFrame(top)
        def _judgment_badge(v):
            s=str(v)
            if s.startswith("적극매수"): return "🔴 적극매수"
            if s.startswith("매수후보"): return "🟡 매수후보"
            if s.startswith("관찰"): return "🔵 관찰"
            if s.startswith("현금대기"): return "⚪ 현금대기"
            return s
        if "판정" in _top_df.columns:
            _top_df["판정표시"]=_top_df["판정"].map(_judgment_badge)
            # 판정 관련 열을 앞쪽으로 이동해 가로 스크롤 없이 확인
            _front=[c for c in ["순위","종목","티커","현재가($)","USA점수","판정점수","판정표시","1차매수가($)","2차매수가($)","평균매수가($)","3%손절가($)","+15%목표($)","+20%목표($)","+25%목표($)"] if c in _top_df.columns]
            _rest=[c for c in _top_df.columns if c not in _front and c!="판정"]
            _top_df=_top_df[_front+_rest]
        with st.expander("전체 분석 데이터 보기", expanded=False):
            st.dataframe(_top_df,use_container_width=True,hide_index=True,height=520,
                column_config={"USA점수":st.column_config.ProgressColumn("USA점수",min_value=0,max_value=100,format="%.1f"),
                               "주도주":st.column_config.ProgressColumn("주도주",min_value=0,max_value=100,format="%.1f"),
                               "기술":st.column_config.ProgressColumn("기술",min_value=0,max_value=100,format="%.1f"),
                               "재무":st.column_config.ProgressColumn("재무",min_value=0,max_value=100,format="%.1f"),
                               "판정점수":st.column_config.ProgressColumn("판정점수",min_value=0,max_value=100,format="%.1f"),
                               "판정표시":st.column_config.TextColumn("판정",width="medium")})
        st.caption("판정 색상: 🔴 적극매수 · 🟡 매수후보 · 🔵 관찰 · ⚪ 현금대기  |  표 전체 배경색은 적용하지 않아 글자가 선명하게 보입니다.")

        _entry_candidates=[x for x in top if str(x.get("판정","")).startswith(("적극매수","매수후보"))][:3]
        st.markdown("### 최종 3종목 후보")
        if _entry_candidates:
            cols=st.columns(3)
            for _i,_r in enumerate(_entry_candidates):
                with cols[_i]:
                    st.metric(f'{_i+1}순위 · {_r.get("티커","")}',f'{_r.get("판정점수","-")}점')
                    st.write(_r.get("판정",""))
                    st.caption(f'1차 ${_r.get("1차매수가($)","-")} · 2차 ${_r.get("2차매수가($)","-")}')
                    st.caption(f'평균 ${_r.get("평균매수가($)","-")} · 3% 손절 ${_r.get("3%손절가($)","-")}')
                    st.caption(f'목표 +15% ${_r.get("+15%목표($)","-")} · +20% ${_r.get("+20%목표($)","-")} · +25% ${_r.get("+25%목표($)","-")}')
        else:
            st.warning("현재 적극매수/매수후보가 없어 3종목을 억지로 선정하지 않습니다.")

with tabs[2]:
    rows=st.session_state.get("us_ranked",[]); details=st.session_state.get("us_details",{})
    valid=[x for x in rows[:12] if x.get("티커") in details]
    if not valid: st.info("TOP12 생성 후 상세를 볼 수 있습니다.")
    else:
        labels=[f'{x["순위"]}. {x["티커"]} · {x["종목"]}' for x in valid]
        sel=st.selectbox("종목",labels); r=valid[labels.index(sel)]
        d,a,lm,fn,pdeta=details[r["티커"]]
        c1,c2,c3,c4=st.columns(4)
        c1.metric("USA점수",r["USA점수"]); c2.metric("판정",r["판정"])
        c3.metric("1차",f'${a["entry"]:,.2f}'); c4.metric("2차",f'${a["entry2"]:,.2f}')
        st.write(f'재무: {fn["status"]} · {fn["fund_score"]}점 / ROE {fn["roe"]} / 매출성장 {fn["revenue_growth"]}')
        st.write("주도주 근거: "+(" / ".join(lm["notes"]) if lm["notes"] else "특별 신호 없음"))
        st.write("매수 근거: "+" / ".join(a["reasons"]))
        st.line_chart(d.set_index("date")[["close"]].tail(180))

with tabs[3]:
    st.subheader("미국장 3천만원 · 3종목 분산 운용")
    total_krw=st.number_input("총 운용자금(원)",min_value=0,value=30_000_000,step=1_000_000)
    stock_count=st.number_input("최대 보유 종목 수",min_value=1,max_value=6,value=3,step=1)
    fx=st.number_input("적용 환율(원/USD)",min_value=500.0,max_value=3000.0,value=1400.0,step=10.0,
                       help="실제 주문 전 증권사 적용 환율로 수정하세요.")

    per_krw=total_krw/stock_count if stock_count else 0
    first_krw=per_krw*0.50
    second_krw=per_krw*0.50
    per_usd=per_krw/fx if fx else 0
    first_usd=first_krw/fx if fx else 0
    second_usd=second_krw/fx if fx else 0

    c1,c2,c3,c4=st.columns(4)
    c1.metric("총 운용자금",f"{total_krw:,.0f}원")
    c2.metric("종목당 최대",f"{per_krw:,.0f}원")
    c3.metric("1차 50%",f"{first_krw:,.0f}원")
    c4.metric("2차 50%",f"{second_krw:,.0f}원")

    d1,d2,d3=st.columns(3)
    d1.metric("종목당 USD",f"${per_usd:,.0f}")
    d2.metric("1차 USD",f"${first_usd:,.0f}")
    d3.metric("2차 USD",f"${second_usd:,.0f}")

    st.markdown("### 최종 3종목 운용 원칙")
    st.write("TOP12 중 **적극매수/매수후보이면서 판정점수가 높은 종목을 최대 3개**만 선택합니다.")
    st.write("3개를 무조건 채우지 않습니다. 진입신호가 1개면 1개만 사고, 나머지 자금은 현금으로 둡니다.")
    st.write("기본값은 **종목당 1,000만원 → 1차 500만원 → 조건 재확인 → 2차 500만원**입니다.")

    st.markdown("### 미국장 수익 실현 규칙")
    st.info("기본 목표 +15% · +10%에서는 추세 확인 · +15% 30~50% 분할매도 · +20% 추가 25% · +25% 추가 25% · 잔여분 추세보유")
    st.write("손절은 **최종 평균매수가 대비 -3%**를 기본 실행 기준으로 사용합니다. ATR은 분석용 변동성 지표로만 유지합니다.")
    st.caption("환율·환전수수료·매매수수료·세금은 실제 증권사 조건에 맞춰 별도로 확인하세요.")

with tabs[5]:
    st.markdown("""



### 아이폰 접속 방법
1. PC에서 `run_mobile.bat`을 실행합니다.
2. PC와 아이폰을 **같은 Wi‑Fi**에 연결합니다.
3. PC 화면에 표시되는 `http://PC-IP:8501` 주소를 아이폰 Safari에 입력합니다.
4. 외부 인터넷에서 접속하려면 별도 보안 배포가 필요합니다. KIS App Secret은 아이폰에 저장하지 않습니다.

### USA V1.9 손절 규칙
- 매매 화면의 **ATR 손절가를 제거**했습니다.
- 실제 손절가는 **최종 평균매수가 × 0.97**로 자동 계산합니다.
- TOP12 표 순서는 **1차매수가 → 2차매수가 → 평균매수가 → 3%손절가 → +15% → +20% → +25% 목표가**입니다.
- ATR(%)은 매수 여부와 변동성 판단을 위한 분석 자료로만 남깁니다.

### USA V1.6 수익관리 규칙
- **기본 목표수익률은 +15%**로 상향합니다.
- **+10%에서는 원칙적으로 전량매도하지 않고 추세를 확인**합니다.
- **+15% 도달 시 30~50%를 분할매도**해 원금 일부를 회수합니다.
- **+20%에서 추가 25%, +25%에서 추가 25% 분할매도**를 기본안으로 둡니다.
- 남은 물량은 **월봉 5개월선·추세 훼손 여부**를 보며 보유합니다.
- 손절은 **평균매수가 대비 -3% 고정 손절**을 사용합니다. ATR은 종목 변동성 평가에만 사용합니다.
- 진입은 기존대로 **1차 50% / 2차 50% 분할진입**을 기본값으로 둡니다.

### V1.5 HYBRID 데이터 구조
- **KIS Open API**: NASDAQ·NYSE·AMEX의 거래대금/시가총액/거래증가/신고가 순위에서 후보를 발굴합니다.
- **Yahoo Finance**: 후보 종목의 18개월 일봉, 현재가, 재무정보를 정밀분석에 사용합니다.
- 이렇게 후보발굴과 정밀분석 데이터원을 분리해 해외주식 KIS 일봉 API 한 곳의 실패가 TOP12 전체를 막지 않도록 했습니다.
- 재무정보가 일부 누락되어도 일봉 분석이 가능하면 종목 전체를 탈락시키지 않습니다.
- 정상 분석된 종목만 점수화하고 **상위 12개만 TOP12**로 저장합니다.

### V1.4 데이터 안정화
- 현재가는 KIS **해외주식 현재체결가** API를 우선 사용합니다.
- 일봉은 KIS **해외주식 기간별시세**를 여러 번 이어 붙여 최소 120거래일을 확보합니다.
- KIS 조회가 일시 실패하거나 데이터가 부족하면 **yfinance를 보조 데이터원으로 자동 전환**합니다.
- 정상 분석된 종목만 저장하며 화면에는 상위 12개만 TOP12로 표시합니다.

### HY DYNAMIC12 USA V2.2 BLINK 구조
- 대상: **NASDAQ + NYSE + AMEX**
- 1차 후보: **거래대금 + 시가총액 + 거래증가 + 신고가**
- 정밀분석: **20/50/200일 추세 + 20/60일 모멘텀 + 거래대금 + ATR + 과이격**
- 재무: yfinance에서 확보되는 **ROE·이익률·성장률·부채/밸류 지표**를 보조점수로 사용
- 최종점수: **주도주 35% + 기술 25% + 시장수급 15% + 거래대금 10% + 재무 15% = 100점**
- TOP12는 매수 12종목이 아닙니다. **실제 운용은 최대 6종목**입니다.
- 한 종목은 **1차 50% + 2차 50%** 분할진입입니다.
- **V2.2:** 적극매수 종목만 초록 점과 종목명이 부드럽게 점멸합니다. 매수후보·관찰·현금대기는 정적으로 표시합니다.
- 자동주문 기능은 없습니다.

### 자동 판정 기준
- **85~100점: 적극매수** — 1차 진입 우선 검토
- **75~84.9점: 매수후보** — 눌림/가격조건 확인 후 진입
- **65~74.9점: 관찰** — 좋은 후보지만 아직 매수조건 부족
- **65점 미만: 현금대기**
- 판정 칸에는 `매수후보 (79.4점)`처럼 **상태 + 수치**를 함께 표시합니다.
- **과이격이면 고득점이어도 `관찰`로 낮춰 추격매수를 방지**합니다.

### 한국판과 다른 점
미국 시장에는 한국의 `외국인/기관 일별 수급`과 같은 방식의 KIS 지표를 그대로 적용하지 않습니다.
대신 **거래대금·거래증가·신고가·시가총액**을 시장 자금흐름의 대리 지표로 사용합니다.
""")
