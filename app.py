
import streamlit as st
from holdings_ui import install_holdings_tab
install_holdings_tab()
import pandas as pd
import altair as alt
from config import settings,save
from kis_us import KISUS, yf_daily, yf_price, yf_info_safe
from rank_us import USScanner
try:
    from rank_us import broad_us_candidates
except ImportError:
    # Streamlit Cloud가 배포 직후 이전 rank_us 모듈을 잠시 캐시해도 앱 시작은 유지한다.
    def broad_us_candidates(candidate_n=120):
        return pd.DataFrame(), ["광범위 스캔 모듈 갱신 대기 · 이번 실행은 KIS 후보만 사용"]
from us_sector_leaders import scan_sector_leaders
from engine import analyze
from leader import leader_metrics
from fundamental_us import score_yf

from pathlib import Path
import json
import os
import requests
import html
from datetime import datetime
from zoneinfo import ZoneInfo
from monthly_breakout_ui import render_monthly_breakout_tab, scan_monthly_breakouts
from usa_backtest_ui import render_usa_backtest_tab

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


SEOUL=ZoneInfo("Asia/Seoul")
NEW_YORK=ZoneInfo("America/New_York")


@st.cache_data(ttl=86400,show_spinner=False)
def cached_yf_info(symbol):
    return yf_info_safe(symbol)


@st.cache_data(ttl=900,show_spinner=False)
def usa_market_snapshot():
    out=[]
    for ticker,name in [("^GSPC","S&P500"),("^IXIC","NASDAQ"),("^VIX","VIX")]:
        try:
            d=yf_daily(ticker);close=pd.to_numeric(d["close"],errors="coerce").dropna()
            if len(close)>=2:out.append({"name":name,"price":float(close.iloc[-1]),"change":(float(close.iloc[-1])/float(close.iloc[-2])-1)*100})
        except Exception:pass
    return out


def analyze_candidate_frame(cand,limit=None,progress=None,message=None):
    if cand is None or cand.empty:return [],{}
    work=cand.head(min(int(limit or len(cand)),len(cand)));rows=[];details={};errors=[];recs=work.to_dict("records")
    for i,r in enumerate(recs):
        sym=r["symbol"];excd=r["exchange"]
        if message is not None:message.write(f"⏳ {i+1}/{len(recs)} · {sym} 정밀분석")
        try:
            d=yf_daily(sym);a=analyze(d);lm=leader_metrics(d);px=yf_price(sym,d);pdeta={"last":px,"source":"yfinance"};fn=score_yf(cached_yf_info(sym))
            final=round(lm["leader_score"]*.35+a["score"]*.25+r["pre_score"]*.15+min(100,a["value_ratio"]*50)*.10+fn["fund_score"]*.15,1)
            signal="적극매수" if final>=85 else ("매수후보" if final>=75 else ("관찰" if final>=65 else "현금대기"))
            if lm["near_high"]>=98 and a["gap"]>6:signal="관찰"
            px=float(pdeta.get("last",d.iloc[-1].close) or d.iloc[-1].close);avg=round((a["entry"]+a["entry2"])/2,2)
            rows.append({"순위":0,"종목":r["name"],"티커":sym,"거래소":excd,"포착경로":r["sources"],"현재가($)":round(px,2),"USA점수":final,"주도주":lm["leader_score"],"기술":a["score"],"재무":fn["fund_score"],"20일RS(%)":lm["rs20"],"60일RS(%)":lm["rs60"],"120일고점대비(%)":lm["near_high"],"거래대금배수":a["value_ratio"],"재무판정":fn["status"],"ROE(%)":fn["roe"],"매출성장(%)":fn["revenue_growth"],"Forward PER":fn["forward_pe"],"판정":f"{signal} ({final:.1f}점)","판정점수":final,"1차매수가($)":a["entry"],"2차매수가($)":a["entry2"],"평균매수가($)":avg,"3%손절가($)":round(avg*.97,2),"+15%목표($)":a["target"],"+20%목표($)":round(a["entry"]*1.20,2),"+25%목표($)":round(a["entry"]*1.25,2),"ATR(%)":a["atr_pct"]})
            details[sym]=(d,a,lm,fn,pdeta)
        except Exception as e:errors.append(f"{sym}: {str(e)[:300]}")
        if progress is not None:progress.progress((i+1)/max(1,len(recs)))
    rows.sort(key=lambda x:x["USA점수"],reverse=True)
    for n,r in enumerate(rows,1):r["순위"]=n
    st.session_state["us_precision_errors"]=errors
    return rows,details


def run_usa_unified_update(cfg,precise,status):
    status.write("⏳ ① 미국시장 데이터 준비 중...")
    if precise:
        if not cfg["key"] or not cfg["secret"]:raise RuntimeError("정밀 전체 업데이트에는 KIS App Key/Secret이 필요합니다.")
        api=KISUS(cfg);scan=USScanner(api);kis_cand,kis_errs=scan.candidates(40,25);broad,broad_errs=broad_us_candidates(120)
        cand=pd.concat([broad,kis_cand],ignore_index=True).sort_values("pre_score",ascending=False).drop_duplicates("symbol").head(120).reset_index(drop=True);errs=kis_errs+broad_errs
        if cand is None or cand.empty:raise RuntimeError("미국시장 후보를 가져오지 못했습니다.")
        save_json(CAND_FILE,cand.to_dict("records"));st.session_state["us_errors"]=errs
    else:
        saved=load_json(CAND_FILE,[]);cand=pd.DataFrame(saved) if saved else None
        if cand is None or cand.empty:raise RuntimeError("저장된 후보가 없습니다. 먼저 정밀 전체 업데이트를 실행하세요.")
        cand=cand.head(25)
    st.session_state["us_candidates"]=cand;status.write(f"✅ ① 시장 후보 {len(cand)}개 준비")
    status.write("⏳ ② 전체시장 후보 정밀분석 중...");bar=st.progress(0)
    rows,details=analyze_candidate_frame(cand,limit=80 if precise else 25,progress=bar,message=status);bar.empty()
    if not rows:raise RuntimeError("정밀분석 정상 결과가 없습니다.")
    st.session_state["us_ranked"]=rows;st.session_state["us_details"]=details;save_json(TOP12_FILE,rows[:12]);save_kakao_watchlist(rows[:12])
    status.write(f"✅ ② 전체시장 분석 완료 · {len(rows)}개");status.write("✅ ③ USA TOP12 선정 완료");status.write("✅ ④ 부의 점프 계산 완료 · 주도주/기술/재무/거래강도 통합")
    status.write("⏳ ⑤ 5개월선 돌파 분석 중...");ma5=scan_monthly_breakouts(include_etf=True,only_new=False);st.session_state["monthly_ma5_rows"]=ma5;status.write(f"✅ ⑤ 5개월선 분석 완료 · {len(ma5)}개")
    completed=datetime.now(SEOUL).strftime("%Y-%m-%d %H:%M:%S KST");st.session_state["usa_full_update_at"]=completed;st.session_state["usa_update_mode"]="정밀 전체" if precise else "빠른";status.write("✅ ⑥ 저장 및 화면 갱신 완료");return completed


st.set_page_config(page_title="HY DYNAMIC12 · 미국주식 실전선별",page_icon="🇺🇸",layout="wide")

st.markdown(
    '<style>[data-testid="stSidebarNav"]{display:none;}</style>',
    unsafe_allow_html=True,
)
with st.sidebar:
    st.page_link("app.py",label="미국주식 실전선별",icon="🇺🇸")
    st.page_link("pages/7_보유종목관리.py",label="보유종목관리",icon="💼")

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
st.title("🇺🇸 HY DYNAMIC12 · 미국주식 실전선별")
st.caption("KR과 동일한 흐름: 미국시장 → TOP12 → 부의 점프 → 5개월선 → 보유종목 · 미국 수급은 거래대금/상대강도/시총 모멘텀으로 대체")
s=settings()

snap=usa_market_snapshot()
if snap:
    cols=st.columns(len(snap)+1)
    for col,x in zip(cols,snap):col.metric(x["name"],f"{x['price']:,.2f}",f"{x['change']:+.2f}%")
    cols[-1].metric("미국 동부시간",datetime.now(NEW_YORK).strftime("%m-%d %H:%M"))
fast_col,full_col=st.columns([2,1])
if fast_col.button("⚡ USA 빠른 업데이트",type="primary",use_container_width=True,key="usa_fast_all"):
    status=st.status("USA 빠른 업데이트 실행 중",expanded=True)
    try:
        done=run_usa_unified_update(s,False,status);status.update(label=f"⚡ 빠른 업데이트 완료 · {done}",state="complete",expanded=True);st.success("저장 후보의 최신 가격과 판정을 갱신했습니다.")
    except Exception as e:status.update(label="빠른 업데이트 오류",state="error",expanded=True);st.error(str(e))
if full_col.button("🚀 USA 정밀 전체 업데이트",use_container_width=True,key="usa_precise_all"):
    status=st.status("USA 정밀 전체 업데이트 실행 중",expanded=True)
    try:
        done=run_usa_unified_update(s,True,status);status.update(label=f"🎉 정밀 전체 업데이트 완료 · {done}",state="complete",expanded=True);st.success("신규 후보 탐색부터 TOP12까지 완료했습니다.")
    except Exception as e:status.update(label="정밀 전체 업데이트 오류",state="error",expanded=True);st.error(str(e))
if st.session_state.get("usa_full_update_at"):st.caption(f"마지막 업데이트: **{st.session_state['usa_full_update_at']}** · {st.session_state.get('usa_update_mode','-')}")


def render_usa_top12_blink(top):
    """TOP12 점수 순위표. 매수 행동 표시는 아래 종합평가에서만 결정한다."""
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
        name=esc(r.get("종목",""))
        ticker=esc(r.get("티커",""))
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
            badge="🟣 TOP12 점수상위"
        elif raw_j.startswith("매수후보"):
            badge="🔵 TOP12 점수후보"
        elif raw_j.startswith("관찰"):
            badge="⚪ TOP12 관찰"
        elif raw_j.startswith("현금대기"):
            badge="⚪ TOP12 대기"
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
    st.warning("TOP12는 점수 순위표이며 매수 신호가 아닙니다. 실제 진입 여부는 아래 ‘USA 통합 종합평가’의 조기포착·매수검토·과열 판정을 따르세요.")


@st.cache_data(ttl=600, show_spinner=False)
def usa_leader_entry_conditions(cache_version="sector-duration-v2"):
    """강한 업종을 먼저 찾고 업종별 대표 주도주 2~3개를 반환합니다."""
    sectors=scan_sector_leaders(max_sectors=12,representatives=3)
    for sector in sectors:
        confirmed=sector.get("evaluation")=="🟢 주도업종"
        for row in sector.get("representatives",[]):
            row["technical_ready"]=bool(row.get("ready"));row["ready"]=bool(row.get("ready")) and confirmed
    return sectors


@st.cache_data(ttl=10,show_spinner=False)
def _usa_live_prices(tickers):
    tickers=tuple(dict.fromkeys(str(x).strip().upper() for x in tickers if str(x).strip()))
    if not tickers:return {}
    prices={}
    for period,interval in (("1d","1m"),("5d","1d")):
        missing=[x for x in tickers if x not in prices]
        if not missing:break
        try:
            data=yf.download(missing,period=period,interval=interval,prepost=False,auto_adjust=True,progress=False,threads=True,group_by="ticker")
            for ticker in missing:
                try:
                    frame=data[ticker] if isinstance(data.columns,pd.MultiIndex) else data;close=pd.to_numeric(frame["Close"],errors="coerce").dropna()
                    if not close.empty:prices[ticker]=float(close.iloc[-1])
                except Exception:continue
        except Exception:continue
    return prices

@st.fragment(run_every="10s")
def render_usa_leader_entry_panel():
    st.subheader("📊 미국 주도업종·대표종목 통합판")
    st.caption("미국 업종별 주도력과 실제 대표 종목을 한 화면에서 비교합니다. 종목별 최종 매수판정은 아래 통합 매수판정에서만 표시합니다.")
    try:
        sectors=usa_leader_entry_conditions()
    except Exception as e:
        st.warning(f"주도 업종을 불러오지 못했습니다: {e}")
        return
    if not sectors:
        st.info("현재 평가 가능한 미국 업종이 없습니다.")
        return
    sector_chart=pd.DataFrame([{
        "업종":s["sector"],
        "주도점수":round(float(s.get("score",0)),1),
        "상승확산(%)":round(float(s.get("breadth",0)),1),
        "20일 수익률(%)":round(float(s.get("return20",0)),1),
        "60일 수익률(%)":round(float(s.get("return60",0)),1),
        "거래량배수":round(float(s.get("volume_ratio",0)),2),
        "상태":(
            "🚀 주도" if float(s.get("score",0))>=70 and float(s.get("breadth",0))>=60
            else "🟢 확산" if float(s.get("score",0))>=60 and float(s.get("breadth",0))>=55
            else "🔵 중립" if float(s.get("score",0))>=50
            else "🟠 둔화" if float(s.get("score",0))>=35
            else "🔴 이탈"
        ),
        "대표종목":", ".join(x.get("ticker","") for x in s.get("representatives",[])),
    } for s in sectors]).sort_values("주도점수",ascending=False).reset_index(drop=True)
    first=sector_chart.iloc[0]
    st.success(f"현재 1위 주도업종: {first['업종']} · {first['주도점수']:.1f}점 · 대표종목 {first['대표종목'] or '-'}")
    st.markdown("**업종별 주도점수 · 대표종목**")
    sector_order=sector_chart["업종"].tolist()
    state_color=alt.Color(
        "상태:N",
        scale=alt.Scale(
            domain=["🚀 주도","🟢 확산","🔵 중립","🟠 둔화","🔴 이탈"],
            range=["#38bdf8","#60a5fa","#64748b","#f59e0b","#ef4444"],
        ),
        legend=None,
    )
    base=alt.Chart(sector_chart).encode(
        y=alt.Y("업종:N",sort=sector_order,title=None,axis=alt.Axis(labelLimit=130,labelFontSize=12)),
        x=alt.X("주도점수:Q",scale=alt.Scale(domain=[0,100]),title="주도점수"),
        color=state_color,
        tooltip=[
            alt.Tooltip("업종:N"),alt.Tooltip("상태:N"),alt.Tooltip("주도점수:Q",format=".1f"),
            alt.Tooltip("상승확산(%):Q",format=".1f"),alt.Tooltip("20일 수익률(%):Q",format=".1f"),
            alt.Tooltip("60일 수익률(%):Q",format=".1f"),alt.Tooltip("거래량배수:Q",format=".2f"),
            alt.Tooltip("대표종목:N"),
        ],
    )
    bars=base.mark_bar(cornerRadiusEnd=4,height=14)
    scores=base.mark_text(align="left",baseline="middle",dx=5,color="#e5e7eb").encode(
        text=alt.Text("주도점수:Q",format=".1f")
    )
    stock_labels=alt.Chart(sector_chart).mark_text(
        align="left",baseline="middle",fontSize=12,color="#e5e7eb"
    ).encode(
        y=alt.Y("업종:N",sort=sector_order,title=None,axis=None),
        text=alt.Text("대표종목:N"),
        tooltip=[alt.Tooltip("업종:N"),alt.Tooltip("대표종목:N"),alt.Tooltip("상태:N")],
    ).properties(width=190,height=alt.Step(24),title="대표종목")
    compact_chart=alt.hconcat(
        (bars+scores).properties(width=620,height=alt.Step(24)),
        stock_labels,
        spacing=10,
    ).resolve_scale(y="shared")
    st.altair_chart(compact_chart,use_container_width=True)
    st.caption("막대에 업종과 대표종목을 함께 표시했습니다. 마우스를 올리면 상승확산·20/60일 수익률·거래량을 확인할 수 있습니다.")

def render_usa_integrated_buy_panel(top):
    title_col,kakao_col=st.columns([3.4,1],gap="large")
    with title_col:
        st.subheader("🎯 USA 통합 종합평가")
        st.caption("TOP12 · 부의 점프 · 월봉 5개월선 · 주도업종을 합산합니다. 5개월선 -3% 이내 접근은 0.5점으로 먼저 포착하고, 과열 종목은 눌림 대기로 전환합니다.")
    kakao_slot=kakao_col.container(border=True)
    if not top:
        st.info("USA TOP12가 없습니다. 먼저 정밀 전체 업데이트를 실행하세요.");return
    try:sectors=usa_leader_entry_conditions()
    except Exception:sectors=[]
    sector_map={x["ticker"]:{"ready":bool(x.get("ready")),"sector":x.get("sector",s.get("sector","-"))} for s in sectors for x in s.get("representatives",[])}
    ma_rows=st.session_state.get("monthly_ma5_rows",[])
    ma_map={str(x.get("티커","")):x for x in ma_rows}
    results=[]
    for row in top[:12]:
        ticker=str(row.get("티커",""));score=float(row.get("USA점수",0) or 0);leader=float(row.get("주도주",0) or 0);technical=float(row.get("기술",0) or 0);fundamental=float(row.get("재무",0) or 0)
        top_ok=True
        wealth_ok=score>=75 and leader>=70 and technical>=55 and fundamental>=50
        wealth_near=(not wealth_ok) and score>=70 and leader>=65 and technical>=50 and fundamental>=45
        wealth_point=1.0 if wealth_ok else (0.5 if wealth_near else 0.0)
        ma=ma_map.get(ticker,{})
        ma_rate=float(ma.get("돌파율(%)",-999) or -999) if ma else -999
        ma_valid=bool(ma) and ma.get("판정")!="⚪ 제외"
        ma_ok=ma_valid and ma_rate>=0
        ma_near=ma_valid and -3<=ma_rate<0
        ma_point=1.0 if ma_ok else (0.5 if ma_near else 0.0)
        sector=sector_map.get(ticker,{});sector_ok=bool(sector.get("ready"))
        total=1.0+wealth_point+ma_point+float(sector_ok)
        current=float(row.get("현재가($)",0) or 0)
        entry1=float(row.get("1차매수가($)",0) or 0)
        overheat=(ma_ok and ma_rate>=7) or (entry1>0 and current>=entry1*1.08)
        if ma_ok:ma_label="✅ 돌파"
        elif ma_near:ma_label=f"△ 접근 {ma_rate:.1f}%"
        else:ma_label="대기"
        wealth_label="✅" if wealth_ok else ("△ 점수접근" if wealth_near else "대기")
        missing=[]
        if not wealth_ok:missing.append("부의 점프 기준 접근" if wealth_near else "부의 점프")
        if not ma_ok:
            missing.append("5개월선 돌파 직전" if ma_near else "5개월선")
        if not sector_ok:missing.append("주도업종")
        missing_text=" · ".join(missing) or "없음"
        point_text=f"{total:g}/4"
        if overheat and total>=2.5:
            decision="🟠 과열·눌림대기";action="추격 금지 · 눌림 지지 확인"
        elif total>=4:
            decision="🟢 강한 매수 검토";action="눌림 확인 후 1차 20~30% 분할"
        elif total>=3:
            decision="🟢 1차 매수 검토";action="눌림 확인 후 1차 10~20%"
        elif total>=2.5:
            decision="🟡 조기 포착";action="매수확정 아님 · 돌파 또는 눌림 관찰"
        elif total>=2:
            decision="🟡 관찰";action="신호 1개 추가 확인"
        else:
            decision="⚪ 매수보류";action="단독 신호로 매수 금지"
        results.append({
            "종합순위":0,"종목":row.get("종목"),"티커":ticker,"현재가($)":row.get("현재가($)"),
            "TOP12":"✅","부의점프":wealth_label,"5개월선":ma_label,
            "주도업종":"✅" if sector_ok else "대기","종합점수":point_text,"점수값":total,
            "부족조건":missing_text,"과열":"⚠️" if overheat else "-","종합판정":decision,"행동":action,
            "1차매수가($)":row.get("1차매수가($)"),"2차매수가($)":row.get("2차매수가($)"),
            "업종":sector.get("sector","-"),
        })
    results.sort(key=lambda x:(x["점수값"],float(next((r.get("USA점수",0) for r in top if r.get("티커")==x["티커"]),0) or 0)),reverse=True)
    for i,row in enumerate(results,1):row["종합순위"]=i
    early=[x for x in results if x["종합판정"]=="🟡 조기 포착"]
    buy=[x for x in results if x["종합판정"].startswith("🟢")]
    overheated=[x for x in results if x["종합판정"].startswith("🟠")]
    alerts=early+buy
    a,b,c,d=st.columns(4)
    a.metric("4/4 강한포착",sum(x["점수값"]=="4/4" and x["종합판정"].startswith("🟢") for x in results))
    b.metric("2.5~3.5 조기·매수",len(alerts))
    c.metric("오늘 매수검토",len(buy))
    d.metric("과열·눌림대기",len(overheated))
    if buy:
        st.success("오늘 통합 매수검토: "+", ".join(f"{x['티커']}({x['종합점수']})" for x in buy[:4]))
    if early:
        st.info("조기 포착(매수확정 아님): "+", ".join(f"{x['티커']}({x['종합점수']})" for x in early[:4]))
    if overheated:
        st.warning("추격 금지·눌림대기: "+", ".join(f"{x['티커']}({x['종합점수']})" for x in overheated[:4]))
    if not alerts and not overheated:
        best=max(x["점수값"] for x in results)
        nearest=[x for x in results if x["점수값"]==best]
        nearest_text=", ".join(f"{x['티커']}({x['종합점수']} · 부족: {x['부족조건']})" for x in nearest[:4])
        st.info(f"현재 조기 포착·매수검토 종목은 없습니다. 가장 가까운 후보: {nearest_text}")
    view=pd.DataFrame(results).drop(columns=["점수값"],errors="ignore")
    st.dataframe(view,use_container_width=True,hide_index=True)

    kakao_ready=bool(KAKAO_REST_API_KEY and KAKAO_REFRESH_TOKEN)
    with kakao_slot:
        st.markdown("##### 🔔 카카오 알림")
        st.caption(("✅ 연결됨" if kakao_ready else "⚠️ 설정 필요")+f" · 현재 신호 {len(alerts)}종목")
        auto=st.toggle(
            "종합평가 자동알림",
            value=True,disabled=not kakao_ready,key="usa_integrated_kakao_auto",
            help="2.5/4 조기 포착 또는 3/4 이상 신규 신호를 하루 한 번 전송합니다.",
        )
    alert_time=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M KST")
    message_lines=[
        "[HY DYNAMIC12 USA 종합평가]",
        f"판정시각: {alert_time}",
        "알림기준: 조기포착 2.5/4 이상 · 과열 제외",
        "",
    ]
    for x in alerts:
        satisfied=", ".join(
            name for name,column in [
                ("TOP12","TOP12"),("부의 점프","부의점프"),
                ("5개월선","5개월선"),("주도업종","주도업종"),
            ] if str(x.get(column,"")).startswith(("✅","△"))
        ) or "없음"
        message_lines.extend([
            f"{x['티커']} | 종합 {x['종합점수']}",
            f"판정: {x['종합판정']}",
            f"충족·접근: {satisfied}",
            f"5개월선: {x['5개월선']}",
            f"부족: {x['부족조건']}",
            f"행동: {x['행동']}",
            "",
        ])
    if not alerts:message_lines.append("현재 조기 포착·매수검토 종목 없음")
    message_lines.append("※ 조기 포착은 매수확정이 아니며, 신호는 실시간으로 변할 수 있습니다.")
    message="\n".join(message_lines)
    with kakao_slot:
        if st.button(
            "📨 현재 신호 보내기",disabled=not kakao_ready or not alerts,
            use_container_width=True,key="usa_integrated_kakao_manual",
        ):
            try:kakao_send_to_me(message);st.success("전송 완료")
            except Exception as e:st.error(str(e))
        st.caption("과열 종목 제외 · 동일 신호 하루 1회")
    signature="|".join(sorted(f"{x['티커']}:{x['종합점수']}:{x['종합판정']}" for x in alerts))
    alert_date=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d")
    alert_key=f"{alert_date}|{signature}" if signature else ""
    kakao_state=_kakao_load_state()
    sent_integrated=list(kakao_state.get("integrated_alert_keys",[]))
    if auto and kakao_ready and alert_key and alert_key not in sent_integrated:
        try:
            kakao_send_to_me(message)
            sent_integrated.append(alert_key)
            kakao_state["integrated_alert_keys"]=sent_integrated[-100:]
            _kakao_save_state(kakao_state)
            with kakao_slot:st.success("새 신호 전송 완료")
        except Exception as e:
            with kakao_slot:st.warning(str(e))
    if not ma_rows:st.warning("5개월선 결과가 없습니다. 빠른 또는 정밀 전체 업데이트를 실행해야 완전한 종합평가가 가능합니다.")


tabs=st.tabs(["🔎 전체시장 분석","🏆 USA TOP12","🚀 부의 점프","🔥 현재 5개월선 돌파","📈 과거 성과 검증","💰 자금관리","📋 전략 규칙","⚙️ KIS 설정","🔔 카카오"])

with tabs[7]:
    st.subheader("KIS 설정")
    env=st.selectbox("환경",["real","demo"],index=0 if s["env"]=="real" else 1)
    k=st.text_input("새 App Key",type="password")
    sec=st.text_input("새 App Secret",type="password")
    ac=st.text_input("계좌 앞 8자리",value=s["account"],max_chars=8)
    pr=st.text_input("상품코드",value=s["product"],max_chars=2)
    if st.button("KIS 설정 저장"):
        save(k,sec,ac,pr,env); st.success("저장 완료"); st.rerun()

with tabs[0]:
    st.subheader("🔎 NASDAQ + NYSE + AMEX 전체시장 분석")
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
        candidate_view=cand.drop(
            columns=["sources","source_count"],errors="ignore"
        ).sort_values("pre_score",ascending=False).copy()

        def _candidate_score_color(value):
            score=float(value)
            if score>=80:return "color: #ff5b5b; font-weight: 700"
            if score>=70:return "color: #ffb84d; font-weight: 700"
            return "color: #5aa2ff; font-weight: 700"

        styled_candidates=candidate_view.style.map(
            _candidate_score_color,subset=["pre_score"]
        )
        st.dataframe(styled_candidates,use_container_width=True,hide_index=True,
            column_config={"pre_score":st.column_config.NumberColumn("1차주도점수",format="%.1f")})
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

with tabs[1]:
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
        c1.metric("TOP12 점수 1위",top[0]["티커"])
        c2.metric("USA점수",top[0]["USA점수"])
        c3.metric("TOP12 점수후보",sum(str(x.get("판정","")).startswith(("적극매수","매수후보")) for x in top))
        c4.metric("행동판정","아래 종합평가")
        score_candidates=[x for x in top if str(x.get("판정","")).startswith(("적극매수","매수후보"))]
        if score_candidates:
            st.info("TOP12 단독 관심종목: "+", ".join(x["티커"] for x in score_candidates[:6])+" · 아래 종합평가 통과 전 매수 금지")
        else:
            st.info("현재 TOP12 점수 관심종목 없음 · 아래 종합평가를 확인하세요.")

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
        render_usa_integrated_buy_panel(top)

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
        summary_fields=[("종목",r.get("종목")),("티커",r.get("티커")),("거래소",r.get("거래소")),("판정",r.get("판정")),("USA점수",r.get("USA점수")),("20일 상대강도",r.get("20일RS(%)")),("60일 상대강도",r.get("60일RS(%)")),("120일 고점대비",r.get("120일고점대비(%)")),("거래대금배수",r.get("거래대금배수")),("재무판정",r.get("재무판정"))]
        st.dataframe(pd.DataFrame(summary_fields,columns=["핵심항목","현재값"]),use_container_width=True,hide_index=True)
        try:
            if sym in st.session_state.get("us_details",{}):
                d,a,lm,fn,pdeta=st.session_state["us_details"][sym]
            else:
                d=yf_daily(sym); a=analyze(d); lm=leader_metrics(d); fn=score_yf(yf_info_safe(sym)); pdeta={"last":yf_price(sym,d),"source":"yfinance"}
            c1,c2,c3,c4=st.columns(4)
            c1.metric("현재가",f"${float(pdeta.get('last',0)):,.2f}");c2.metric("주도주",lm["leader_score"]);c3.metric("기술",a["score"]);c4.metric("재무",fn["fund_score"])
            chart=d.copy()
            chart["ma20"]=pd.to_numeric(chart["close"],errors="coerce").rolling(20).mean()
            chart["ma60"]=pd.to_numeric(chart["close"],errors="coerce").rolling(60).mean()
            if "date" in chart.columns:
                chart["date"]=pd.to_datetime(chart["date"],errors="coerce")
                chart=chart.dropna(subset=["date"]).set_index("date")
            chart.index.name="날짜"
            st.line_chart(chart[["close","ma20","ma60"]].tail(120))
            st.markdown("#### 매매계획과 위험지표")
            plan_rows=[("1차 매수가",f"${a['entry']:,.2f}"),("2차 매수가",f"${a['entry2']:,.2f}"),("+15% 목표가",f"${a['target']:,.2f}"),("ATR",f"{a['atr_pct']:.2f}%"),("이동평균 이격",f"{a['gap']:.2f}%"),("거래대금 배수",f"{a['value_ratio']:.2f}배"),("120일 고점 대비",f"{lm['near_high']:.1f}%")]
            st.dataframe(pd.DataFrame(plan_rows,columns=["항목","기준값"]),use_container_width=True,hide_index=True)
            if lm["near_high"]>=98 and a["gap"]>6:st.warning("고점권이면서 이동평균선 이격이 큽니다. 현재가 추격보다 1·2차 매수가 구간의 눌림을 기다리세요.")
            elif a["gap"]>6:st.info("이동평균선 이격 부담이 있어 분할매수 구간까지 기다리는 편이 안전합니다.")
            else:st.success("이격이 과도하지 않습니다. 판정점수와 1·2차 매수가를 함께 확인하세요.")
        except Exception as e: st.error(str(e))

with tabs[5]:
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

with tabs[8]:
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

with tabs[3]:
    render_monthly_breakout_tab()

with tabs[4]:
    render_usa_backtest_tab()

