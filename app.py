
import streamlit as st
from holdings_ui import install_holdings_tab
install_holdings_tab()
import pandas as pd
from config import settings,save
from kis_us import KISUS, yf_daily, yf_price, yf_info_safe
from rank_us import USScanner
from us_sector_leaders import scan_sector_leaders
from engine import analyze
from leader import leader_metrics
from fundamental_us import score_yf

from pathlib import Path
import json
import os
import requests
import html

STATE_DIR=Path("data")
STATE_DIR.mkdir(exist_ok=True)
TOP12_FILE=STATE_DIR/"usa_top12.json"
CAND_FILE=STATE_DIR/"usa_candidates.json"

KAKAO_STATE_FILE=STATE_DIR/"kakao_monitor_state.json"
KAKAO_WATCH_FILE=Path("kakao_watchlist.json")
KAKAO_REST_API_KEY=os.getenv("KAKAO_REST_API_KEY","").strip()
KAKAO_CLIENT_SECRET=os.getenv("KAKAO_CLIENT_SECRET","").strip()
KAKAO_REFRESH_TOKEN=os.getenv("KAKAO_REFRESH_TOKEN","").strip()

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



def _kakao_load_state():
    try:
        if KAKAO_STATE_FILE.exists():
            return json.loads(KAKAO_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def _kakao_save_state(obj):
    try:
        KAKAO_STATE_FILE.write_text(
            json.dumps(obj,ensure_ascii=False,indent=2,default=str),
            encoding="utf-8"
        )
    except Exception:
        pass

def _kakao_get_access_token():
    if not KAKAO_REST_API_KEY or not KAKAO_REFRESH_TOKEN:
        raise RuntimeError("Kakao Secrets 미설정: KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN")

    data={
        "grant_type":"refresh_token",
        "client_id":KAKAO_REST_API_KEY,
        "refresh_token":KAKAO_REFRESH_TOKEN,
    }
    if KAKAO_CLIENT_SECRET:
        data["client_secret"]=KAKAO_CLIENT_SECRET

    r=requests.post(
        "https://kauth.kakao.com/oauth/token",
        data=data,
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Kakao token error {r.status_code}: {r.text[:300]}")
    return r.json().get("access_token")

def kakao_send_to_me(text):
    token=_kakao_get_access_token()
    template={
        "object_type":"text",
        "text":text,
        "link":{
            "web_url":"https://github.com/EGGPAPA/HY-DYNAMIC12-USA",
            "mobile_web_url":"https://github.com/EGGPAPA/HY-DYNAMIC12-USA",
        },
        "button_title":"HY DYNAMIC12 USA",
    }
    r=requests.post(
        "https://kapi.kakao.com/v2/api/talk/memo/default/send",
        headers={"Authorization":f"Bearer {token}"},
        data={"template_object":json.dumps(template,ensure_ascii=False)},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Kakao send error {r.status_code}: {r.text[:300]}")
    return True

def save_kakao_watchlist(top):
    """
    TOP12 중 적극매수만 Kakao watchlist에 저장.
    GitHub Actions의 기존 kakao_monitor.py와 호환되도록
    ticker/name/entry1/entry2/stop/score 필드를 저장합니다.
    """
    active=[]
    for r in top[:12]:
        if str(r.get("판정","")).startswith("적극매수"):
            active.append({
                "ticker":r.get("티커",""),
                "name":r.get("종목",""),
                "score":r.get("판정점수",r.get("USA점수")),
                "entry1":r.get("1차매수가($)"),
                "entry2":r.get("2차매수가($)"),
                "stop":r.get("3%손절가($)"),
                "judgment":r.get("판정",""),
            })
    try:
        KAKAO_WATCH_FILE.write_text(
            json.dumps(active,ensure_ascii=False,indent=2,default=str),
            encoding="utf-8"
        )
    except Exception:
        pass
    return active

def maybe_send_new_active_buy(top):
    """
    새로 적극매수에 진입한 종목만 1회 Kakao 전송.
    기존 상태와 비교해 중복 알림을 방지합니다.
    """
    active=save_kakao_watchlist(top)
    current={x["ticker"]:x for x in active if x.get("ticker")}
    state=_kakao_load_state()
    prev=set(state.get("active_tickers",[]))
    now=set(current.keys())
    newly=sorted(now-prev)

    sent=[]
    for ticker in newly:
        r=current[ticker]
        msg=(
            f"🟢 HY DYNAMIC12 USA 적극매수\n"
            f"{r.get('name','')} ({ticker})\n"
            f"판정점수: {r.get('score','-')}\n"
            f"1차 매수가: ${r.get('entry1','-')}\n"
            f"2차 매수가: ${r.get('entry2','-')}\n"
            f"3% 손절가: ${r.get('stop','-')}"
        )
        try:
            kakao_send_to_me(msg)
            sent.append(ticker)
        except Exception:
            pass

    _kakao_save_state({
        "active_tickers":sorted(now),
        "last_sent":sent,
    })
    return active, sent


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
st.title("HY DYNAMIC12 USA V2.3 · BLINK + KAKAO")
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


@st.cache_data(ttl=600, show_spinner=False)
def usa_leader_entry_conditions():
    """강한 업종을 먼저 찾고 업종별 대표 주도주 2~3개를 반환합니다."""
    return scan_sector_leaders(max_sectors=5,representatives=3)


def render_usa_leader_entry_panel():
    st.subheader("🚦 미국 주도 업종 · 대표 종목")
    st.caption("업종의 20일·60일 성과와 상승 종목 비율을 먼저 평가하고, 강한 업종마다 대표 종목 2~3개만 선별합니다.")
    try:
        sectors=usa_leader_entry_conditions()
    except Exception as e:
        st.warning(f"주도 업종을 불러오지 못했습니다: {e}")
        return
    if not sectors:
        st.info("현재 강세 기준을 통과한 미국 주도 업종이 없습니다.")
        return
    ready=[x for s in sectors for x in s["representatives"] if x["ready"]]
    c1,c2,c3=st.columns(3)
    c1.metric("주도 업종",f"{len(sectors)}개")
    c2.metric("4조건 충족",f"{len(ready)}종목")
    c3.metric("업종별 대표","최대 3종목")
    if ready:
        st.success("1차 분할매수 검토: "+", ".join(f"{x['sector']} · {x['ticker']}" for x in ready))
    else:
        st.info("현재 네 조건을 모두 충족한 종목은 없습니다. 자동 감시는 계속됩니다.")
    summary=[{
        "업종":s["sector"],"업종 20일(%)":round(s["return20"],1),
        "업종 60일(%)":round(s["return60"],1),"상승종목 비율(%)":round(s["breadth"],0),
        "평가":"🟢 강세" if s["strength"]=="강세" else "🔵 중립",
        "대표 종목":", ".join(x["ticker"] for x in s["representatives"]),
        "업종점수":round(s["score"],1),
    } for s in sectors]
    st.dataframe(pd.DataFrame(summary),use_container_width=True,hide_index=True)
    for sector in sectors:
        with st.expander(f"{sector['sector']} · 대표 종목 {len(sector['representatives'])}개",expanded=sector is sectors[0]):
            rows=[]
            for x in sector["representatives"]:
                rows.append({
                    "종목":x["ticker"],"현재가($)":round(x["price"],2),
                    "20일 수익률(%)":round(x["return20"],1),"60일 수익률(%)":round(x["return60"],1),
                    "최초 포착일":x["leader_start"],"주도 지속(거래일)":x["leader_days"],
                    "1차 관찰가($)":round(x["observation"],2),
                    "관찰가 ±2%":"✅" if x["near_observation"] else "대기",
                    "20일선 위":"✅" if x["above_ma20"] else "대기",
                    "거래량 ≥0.7배":"✅" if x["volume_ok"] else "대기",
                    "무효선 위":"✅" if x["above_invalidation"] else "대기",
                    "최종 신호":"🟢 1차 분할매수 검토" if x["ready"] else "⏳ 관찰",
                    "주도점수":round(x["score"],1),
                })
            st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)


tabs=st.tabs(["오늘 TOP12","미국시장 스캔","상세","자금관리","KIS 설정","🔔 카카오","전략 규칙"])

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
            save_json(TOP12_FILE,valid_rows[:12]); save_kakao_watchlist(valid_rows[:12])
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
                    if not valid:
                        raise RuntimeError("정밀분석 정상 결과가 0개입니다. Yahoo Finance 조회 또는 후보 티커를 확인하세요.")
                    st.session_state["us_ranked"]=valid
                    st.session_state["us_details"]=details
                    save_json(TOP12_FILE,valid[:12])
                    save_kakao_watchlist(valid[:12])
                    st.session_state.pop("usa_auto_error",None)
                    bar.empty(); msg.success(f"USA TOP12 자동 생성 완료 · 정상분석 {len(valid)}개")
                    st.rerun()
                except Exception as e:
                    st.session_state["usa_auto_error"]=str(e)
                    st.error(str(e))
    else:
        c1,c2,c3,c4=st.columns(4)
        c1.metric("오늘 1위",top[0]["티커"])
        c2.metric("USA점수",top[0]["USA점수"])
        c3.metric("진입후보",sum(str(x.get("판정","")).startswith(("적극매수","매수후보")) for x in top))
        c4.metric("운용원칙","최대 6종목")
        buy=[x for x in top if str(x.get("판정","")).startswith("적극매수")]
        if buy:
            st.success("우선 진입후보: "+", ".join(x["티커"] for x in buy))
        else:
            st.warning("TOP12 안에도 적극매수/매수후보 없음 — 현금대기")

        if st.button("🔄 오늘 TOP12 다시 계산",use_container_width=True):
            import yfinance as yf
            try:
                source_rows=st.session_state.get("us_candidates")
                if source_rows is None or (isinstance(source_rows,pd.DataFrame) and source_rows.empty):
                    saved=load_json(CAND_FILE,[])
                    source_rows=pd.DataFrame(saved) if saved else None
                if source_rows is None or source_rows.empty:
                    raise RuntimeError("저장된 후보가 없습니다. 미국시장 스캔에서 ① 후보 생성을 먼저 실행하세요.")

                result=[]; details={}
                st.session_state["us_precision_errors"]=[]
                bar=st.progress(0); msg=st.empty()
                recs=source_rows.to_dict("records")
                for i,r in enumerate(recs):
                    sym=r["symbol"]; excd=r["exchange"]
                    msg.info(f"{i+1}/{len(recs)} {sym} 재계산")
                    try:
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
                        result.append({"순위":0,"종목":r.get("name",sym),"티커":sym,"거래소":excd,
                                       "USA점수":None,"판정":"조회오류","오류":errtxt[:300]})
                        st.session_state.setdefault("us_precision_errors",[]).append(f"{sym}: {errtxt}")
                    bar.progress((i+1)/max(1,len(recs)))

                result.sort(key=lambda x:x["USA점수"] if isinstance(x.get("USA점수"),(int,float)) else -1,reverse=True)
                for n,r in enumerate(result,1): r["순위"]=n
                valid=[x for x in result if isinstance(x.get("USA점수"),(int,float))]
                if not valid:
                    raise RuntimeError("재계산 정상 결과가 0개입니다. Yahoo Finance 조회를 확인하세요.")
                st.session_state["us_ranked"]=valid
                st.session_state["us_details"]=details
                save_json(TOP12_FILE,valid[:12])
                save_kakao_watchlist(valid[:12])
                bar.empty(); msg.success("재계산 완료")
                st.rerun()
            except Exception as e:
                st.error(str(e))

        st.subheader("🏆 USA TOP12 핵심표")
        render_usa_top12_blink(top)
        render_usa_leader_entry_panel()

        _precision_errors=st.session_state.get("us_precision_errors",[])
        if _precision_errors:
            with st.expander(f"정밀분석 조회오류 {len(_precision_errors)}건"):
                for _e in _precision_errors[:30]:
                    st.code(_e)

with tabs[2]:
    st.subheader("종목 상세")
    rows=st.session_state.get("us_ranked",[])
    if not rows:
        rows=load_json(TOP12_FILE,[])
    if not rows: st.info("TOP12를 먼저 생성하세요.")
    else:
        sym=st.selectbox("종목",[x["티커"] for x in rows[:12]])
        r=next(x for x in rows if x["티커"]==sym)
        st.json(r)
        try:
            if sym in st.session_state.get("us_details",{}):
                d,a,lm,fn,pdeta=st.session_state["us_details"][sym]
            else:
                d=yf_daily(sym); a=analyze(d); lm=leader_metrics(d); fn=score_yf(yf_info_safe(sym)); pdeta={"last":yf_price(sym,d),"source":"yfinance"}
            c1,c2,c3,c4=st.columns(4)
            c1.metric("현재가",pdeta.get("last"));c2.metric("주도주",lm["leader_score"]);c3.metric("기술",a["score"]);c4.metric("재무",fn["fund_score"])
            st.line_chart(d[["close","ma20","ma60"]].tail(120))
            st.write({"entry1":a["entry"],"entry2":a["entry2"],"target15%":a["target"],"ATR%":a["atr_pct"],"gap%":a["gap"],"value_ratio":a["value_ratio"],"near_high":lm["near_high"]})
        except Exception as e: st.error(str(e))

with tabs[3]:
    st.subheader("자금관리 · 1,000만원 기준")
    total=st.number_input("총 운용자금(원)",value=10000000,step=100000)
    st.write("권장: 4~6종목 / 종목당 15~20% / 1차 50% + 2차 50% / 평균매수가 대비 -3% 손절")
    df=pd.DataFrame({"보유종목수":[4,5,6],"종목당 비중":["20%","18%","15%"],"종목당 금액(원)":[int(total*.20),int(total*.18),int(total*.15)],"1차 금액":[int(total*.10),int(total*.09),int(total*.075)]})
    st.dataframe(df,use_container_width=True,hide_index=True)

    st.markdown("### USA V1.6 수익관리 · 원금회수형")
    st.write("+15% 도달 시 30~50% 분할매도 → +20% 추가 25% → +25% 추가 25% → 잔여분 추세보유")

    rows=st.session_state.get("us_ranked",[])
    if not rows:
        rows=load_json(TOP12_FILE,[])
    top=[r for r in rows if isinstance(r.get("USA점수"),(int,float))][:12]
    if top:
        hold_candidates=[r for r in top if str(r.get("판정","")).startswith(("적극매수","매수후보"))]
        if not hold_candidates:
            hold_candidates=top[:6]

        hold_sym=st.selectbox("수익관리 종목",[r["티커"] for r in hold_candidates],key="usa_profit_symbol")
        rr=next(r for r in hold_candidates if r["티커"]==hold_sym)
        default_entry=float(rr.get("평균매수가($)") or rr.get("1차매수가($)") or rr.get("현재가($)") or 0)
        current=float(rr.get("현재가($)") or 0)
        entry=st.number_input("내 평균매수가($)",min_value=0.0,value=round(default_entry,2),step=0.01,key="usa_profit_entry")
        plan=usa_exit_plan(entry,current)

        c1,c2,c3,c4=st.columns(4)
        c1.metric("현재가($)",f"{current:.2f}")
        c2.metric("수익률",f"{plan['return_pct']:.1f}%")
        c3.metric("현재 단계",plan["stage"])
        c4.metric("3% 손절가",f"{entry*0.97:.2f}" if entry else "-")
        st.success(f"권장 행동: {plan['action']}")

        if entry:
            targets=pd.DataFrame([{
                "평균매수가($)":round(entry,2),
                "+15%($)":round(entry*1.15,2),
                "+20%($)":round(entry*1.20,2),
                "+25%($)":round(entry*1.25,2),
                "-3% 손절($)":round(entry*0.97,2),
            }])
            st.dataframe(targets,use_container_width=True,hide_index=True)
    else:
        st.info("TOP12 생성 후 종목별 수익관리 가격이 표시됩니다.")

with tabs[5]:
    st.subheader("🔔 카카오 연결")
    c1,c2,c3=st.columns(3)
    c1.metric("REST API KEY","설정됨" if KAKAO_REST_API_KEY else "미설정")
    c2.metric("REFRESH TOKEN","설정됨" if KAKAO_REFRESH_TOKEN else "미설정")
    c3.metric("CLIENT SECRET","설정됨" if KAKAO_CLIENT_SECRET else "선택")
    st.caption("Streamlit Secrets 또는 GitHub Actions Secrets에 KAKAO_REST_API_KEY / KAKAO_REFRESH_TOKEN / 필요 시 KAKAO_CLIENT_SECRET을 등록합니다.")
    st.success("앱을 닫아도 GitHub Actions가 미국 정규장에 주도주 네 조건을 자동 감시합니다.")

    rows=st.session_state.get("us_ranked",[])
    if not rows:
        rows=load_json(TOP12_FILE,[])
    top=[r for r in rows if isinstance(r.get("USA점수"),(int,float))][:12]
    active=save_kakao_watchlist(top) if top else []
    st.write(f"현재 TOP12 적극매수 watchlist: **{len(active)}종목**")
    if active:
        st.dataframe(pd.DataFrame(active),use_container_width=True,hide_index=True)
    else:
        st.info("현재 적극매수 종목이 없어 카카오 매수 알림 대상이 없습니다.")

    if st.button("📨 카카오 테스트 메시지 보내기",use_container_width=True):
        try:
            kakao_send_to_me("☑ HY DYNAMIC12 USA 카카오 연결 테스트 성공")
            st.success("카카오톡 '나에게 보내기' 전송 완료")
        except Exception as e:
            st.error(str(e))

with tabs[6]:
    st.subheader("전략 규칙")
    st.markdown("""
- **V1.5 데이터 구조**: KIS = NASDAQ/NYSE/AMEX 후보 40개 발굴, Yahoo Finance = 일봉·현재가·재무 정밀분석
- 1차: 거래대금 / 시총 / 거래증가 / 신고가 순위 통합
- 2차: 주도주 35% + 기술 25% + 1차주도 15% + 거래강도 10% + 재무 15%
- 최종판정: 적극매수 85점↑ / 매수후보 75점↑ / 관찰 65점↑ / 현금대기
- 과이격: 120일 고점권 + 이격 과대면 추격매수 금지
- 손절: 평균매수가 대비 -3%
- 익절: +15% 30~50% 분할매도 → +20% 추가 25% → +25% 추가 25% → 잔여분 추세보유
- 보유: 최대 6종목
- TOP12 표: 적극매수 종목만 초록 점 + 종목명이 부드럽게 점멸
- 카카오: 새 적극매수 종목 발생 시 1회 알림, GitHub Actions 장중 모니터와 watchlist 연동
- 주도주 자동알림: 1차 관찰가 ±2% + 20일선 위 + 거래량 0.7배 이상 + 추세 무효선 위를 모두 충족할 때 발송
""")

