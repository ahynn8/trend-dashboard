import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from dotenv import load_dotenv
import os
import json
import re

load_dotenv()
CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

COLOR_BG = "#F5F1EA"
COLOR_CARD = "#FFFFFF"
COLOR_PRIMARY = "#4BAF9F"
COLOR_SECONDARY = "#A8D8CF"
COLOR_DARK = "#2D3442"
COLOR_TEXT = "#1F2937"
COLOR_SUB = "#6B7280"
CHART_COLORS = ["#4BAF9F", "#2D7A6E", "#A8D8CF", "#3A9080", "#DDF0EC"]


# ============================
# API 함수
# ============================

def get_trend_data(keywords, start_date, end_date, time_unit, gender="", ages=[], device=""):
    url = "https://openapi.naver.com/v1/datalab/search"
    header = {
        "X-Naver-Client-Id": CLIENT_ID,
        "X-Naver-Client-Secret": CLIENT_SECRET,
        "Content-Type": "application/json"
    }
    keyword_groups = [{"groupName": kw, "keywords": [kw]} for kw in keywords]
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": time_unit,
        "keywordGroups": keyword_groups
    }
    if gender:
        body["gender"] = gender
    if ages:
        body["ages"] = ages
    if device:
        body["device"] = device

    response = requests.post(url, headers=header, json=body)
    return response.json()


def parse_trend_data(raw_data):
    results = []
    if "results" not in raw_data or not raw_data["results"]:
        return pd.DataFrame(columns=["키워드", "날짜", "검색량"])
    for item in raw_data["results"]:
        keyword_name = item["title"]
        for point in item.get("data", []):
            results.append({
                "키워드": keyword_name,
                "날짜": point["period"],
                "검색량": point["ratio"]
            })
    if not results:
        return pd.DataFrame(columns=["키워드", "날짜", "검색량"])
    df = pd.DataFrame(results)
    df["날짜"] = pd.to_datetime(df["날짜"])
    return df


# ============================
# 분석 함수
# ============================

def generate_target_interpretation(keywords, df_pc, df_mobile, gender, ages, device):
    age_map = {"1": "10대", "2": "20대", "3": "30대", "4": "40대", "5": "50대", "6": "60대 이상"}
    gender_map = {"m": "남성", "f": "여성", "": "전체"}
    device_map = {"pc": "PC", "mo": "모바일", "": "전체"}
    results = []
    for kw in keywords:
        parts = []
        if gender:
            parts.append(gender_map[gender])
        if ages:
            age_str = "/".join([age_map[a] for a in ages])
            parts.append(age_str)
        if df_pc is not None and df_mobile is not None:
            pc_avg = df_pc[df_pc["키워드"] == kw]["검색량"].mean() if kw in df_pc["키워드"].values else 0
            mobile_avg = df_mobile[df_mobile["키워드"] == kw]["검색량"].mean() if kw in df_mobile["키워드"].values else 0
            total = pc_avg + mobile_avg
            if total > 0:
                mobile_pct = (mobile_avg / total) * 100
                pc_pct = (pc_avg / total) * 100
                if mobile_pct >= 70:
                    parts.append(f"모바일 검색 비중 {mobile_pct:.0f}%로 압도적")
                elif pc_pct >= 70:
                    parts.append(f"PC 검색 비중 {pc_pct:.0f}%로 높음")
                else:
                    parts.append(f"모바일 {mobile_pct:.0f}% / PC {pc_pct:.0f}% 균형")
        elif device:
            parts.append(f"{device_map[device]} 검색 기준")
        if parts:
            results.append((kw, " · ".join(parts)))
    return results


def classify_trend_type(kw_df):
    z = kw_df["z"].dropna()
    search = kw_df["검색량"]
    if len(z) < 3:
        return "➡️", "안정형", "데이터가 충분하지 않아 유형 분류가 어렵습니다.", []
    max_z = z.max()
    max_z_idx = z.idxmax()
    if max_z < 1.5:
        return (
            "➡️", "안정형",
            "특이 급등 없이 검색량이 일정하게 유지되고 있는 기반 키워드입니다.",
            ["현재 유입 효율 상시 모니터링 유지", "안정적 브랜딩 콘텐츠 꾸준히 운영"]
        )
    peak_dates = []
    in_peak = False
    last_peak_idx = None
    for idx in kw_df.index:
        z_val = kw_df.loc[idx, "z"]
        if pd.isna(z_val):
            continue
        if z_val >= 1.5 and not in_peak:
            in_peak = True
            if last_peak_idx is None:
                peak_dates.append(idx)
                last_peak_idx = idx
            else:
                days_gap = (kw_df.loc[idx, "날짜"] - kw_df.loc[last_peak_idx, "날짜"]).days
                if days_gap >= 7:
                    peak_dates.append(idx)
                    last_peak_idx = idx
        elif z_val < 1.5:
            in_peak = False
    if len(peak_dates) >= 2:
        return (
            "🔄", "반복 패턴형",
            "일정 간격으로 검색 관심이 반복적으로 높아지는 패턴입니다. 시즌성 또는 주기적 이슈일 가능성이 있습니다.",
            ["다음 피크 예상 시점 2주 전부터 콘텐츠 빌드업 준비", "경쟁사 동일 시점 대응 패턴 모니터링"]
        )
    after_peak = kw_df.loc[max_z_idx:].iloc[1:]
    if len(after_peak) == 0:
        return (
            "📈", "지속성 상승형",
            "최근 급등이 감지됐으며 이후 패턴은 아직 확인 중입니다.",
            ["검색량 추이 지속 모니터링 필요", "콘텐츠 선점 준비 검토"]
        )
    peak_search = search.loc[max_z_idx]
    after_3d = after_peak.head(3)
    if len(after_3d) > 0:
        min_after_3d = after_3d["검색량"].min()
        no_recovery = after_peak["검색량"].mean() < peak_search * 0.6
        if min_after_3d <= peak_search * 0.5 and no_recovery:
            return (
                "🔥", "단기 이슈형",
                "급등 후 빠르게 검색량이 감소한 패턴으로, 이벤트성 유입 가능성이 있습니다.",
                ["장기 투자보다 이슈 발생 즉시 단타성 SNS 대응 콘텐츠 활용", "유사 이슈 재발 시 즉각 대응 플랜 미리 준비"]
            )
    after_7d = after_peak.head(7)
    if len(after_7d) >= 3:
        mean_after_7d = after_7d["검색량"].mean()
        if mean_after_7d >= peak_search * 0.6:
            return (
                "📈", "지속성 상승형",
                "급등 이후에도 검색량이 유지되고 있어, 일시적 이슈보다 관심 확장 가능성을 시사합니다.",
                ["SEO 콘텐츠 및 블로그 키워드 선점 즉시 시작", "검색광고(SA) 예산 상향 검토", "브랜드 연관 검색어 확장 탐색"]
            )
    return (
        "🔥", "단기 이슈형",
        "급등 후 뚜렷한 지속 패턴이 확인되지 않아, 이벤트성 유입 가능성이 있습니다.",
        ["이슈 재발 시 즉각 대응 플랜 준비", "장기 콘텐츠 투자보다 단기 트래픽 흡수 전략 검토"]
    )


MEMO_FILE = "trends_memo.json"

def load_memo():
    if os.path.exists(MEMO_FILE):
        with open(MEMO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_memo(memo_dict):
    with open(MEMO_FILE, "w", encoding="utf-8") as f:
        json.dump(memo_dict, f, ensure_ascii=False, indent=2)


def get_insight(df, period_unit="date"):
    window_map = {"date": 7, "week": 4, "month": 3}
    min_data_map = {"date": 14, "week": 12, "month": None}
    tail_map = {"date": 7, "week": 4, "month": 3}
    current_insights = []
    past_insights = []
    if period_unit == "month":
        return [("💡", "전체 키워드", "월별 조회는 장기 흐름 파악용입니다. 단기 급등 분석은 일별/주별로 조회해주세요.", "안내")], []
    for kw in df["키워드"].unique():
        kw_df = df[df["키워드"] == kw].sort_values("날짜").copy()
        if len(kw_df) < min_data_map[period_unit]:
            suggest = "14일" if period_unit == "date" else "12주(3개월)"
            current_insights.append(("⚠️", kw, f"조회 기간이 짧아 정확한 분석이 어렵습니다. 최소 {suggest} 이상으로 조회해주세요.", "데이터 부족"))
            continue
        w = window_map[period_unit]
        kw_df["MA"] = kw_df["검색량"].shift(1).rolling(window=w, min_periods=w).mean()
        kw_df["Std"] = kw_df["검색량"].shift(1).rolling(window=w, min_periods=w).std()
        kw_df["z"] = (kw_df["검색량"] - kw_df["MA"]) / kw_df["Std"].replace(0, float('nan'))
        t = tail_map[period_unit]
        recent = kw_df.tail(t)
        recent_z_max = recent["z"].max()
        min_persistence = 2 if period_unit == "date" else 1
        persistence = (recent["z"] >= 1.5).sum()
        if persistence >= min_persistence and recent_z_max >= 2.5:
            current_insights.append(("🚨", kw, f"이례적인 급등이 지속되고 있습니다. (z={recent_z_max:.1f}) ", "폭발"))
        elif persistence >= min_persistence and recent_z_max >= 1.5:
            current_insights.append(("📈", kw, f"평소보다 높은 검색량이 지속되고 있습니다. (z={recent_z_max:.1f}) ", "유입"))
        else:
            current_insights.append(("✅", kw, "안정적인 검색량을 유지하고 있습니다.", "안정"))
        max_z_idx = kw_df["z"].idxmax()
        if not pd.isna(max_z_idx):
            max_z_row = kw_df.loc[max_z_idx]
            max_z_value = max_z_row["z"]
            max_z_date = max_z_row["날짜"].strftime("%m월 %d일")
            type_emoji, type_name, interpret, actions = classify_trend_type(kw_df)
            if max_z_value >= 2.5:
                past_insights.append(("🚨", kw, f"{max_z_date} 이례적인 검색량 급등이 감지됐습니다. (z={max_z_value:.1f}) ", "폭발", type_emoji, type_name, interpret, actions))
            elif max_z_value >= 1.5:
                past_insights.append(("📈", kw, f"{max_z_date} 평균 변동 범위를 벗어난 상승이 감지됐습니다. (z={max_z_value:.1f}) ", "유입", type_emoji, type_name, interpret, actions))
    return current_insights, past_insights


# ============================
# 페이지 설정
# ============================

st.set_page_config(page_title="네이버 검색 트렌드 대시보드", layout="wide")

st.markdown(f"""
<style>
    /* 사이드바 완전 제거 */
    [data-testid="stSidebar"] {{ display: none !important; }}
    [data-testid="stSidebarCollapsedControl"] {{ display: none !important; }}
    /* 앱 전체 배경 */
    .stApp {{ background-color: {COLOR_BG}; }}
    .block-container {{ padding-top: 1rem; padding-left: 2rem; padding-right: 2rem; max-width: 100%; }}
    /* 메트릭 카드 */
    div[data-testid="metric-container"] {{
        background-color: {COLOR_CARD};
        border-radius: 10px;
        padding: 14px 16px;
        border: 0.5px solid rgba(0,0,0,0.08);
    }}
    div[data-testid="metric-container"] label {{ font-size: 12px !important; color: {COLOR_SUB} !important; }}
    div[data-testid="metric-container"] div[data-testid="stMetricValue"] {{ font-size: 22px !important; color: {COLOR_TEXT} !important; }}
    div[data-testid="metric-container"] div[data-testid="stMetricDelta"] {{ font-size: 12px !important; }}
    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] {{ border-bottom: 1.5px solid rgba(0,0,0,0.08); }}
    .stTabs [data-baseweb="tab"] {{ font-size: 14px !important; font-weight: 500 !important; color: {COLOR_SUB} !important; }}
    .stTabs [aria-selected="true"] {{ color: {COLOR_PRIMARY} !important; border-bottom: 2px solid {COLOR_PRIMARY} !important; }}
    /* 필터 바 */
    div[data-testid="stHorizontalBlock"].filter-row {{
        background: {COLOR_DARK};
        border-radius: 12px;
        padding: 8px 16px 12px;
    }}
    /* 버튼 */
    .stButton button {{
        background-color: {COLOR_PRIMARY} !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 500 !important;
    }}
    .stButton button:hover {{
        background-color: {COLOR_DARK} !important;
    }}
    /* 다운로드 버튼 */
    .stDownloadButton button {{
        background-color: transparent !important;
        color: {COLOR_PRIMARY} !important;
        border: 1px solid {COLOR_PRIMARY} !important;
        border-radius: 8px !important;
    }}
    /* 링크 버튼 */
    .stLinkButton a {{
        background-color: transparent !important;
        color: {COLOR_PRIMARY} !important;
        border: 1px solid {COLOR_PRIMARY} !important;
        border-radius: 8px !important;
        font-size: 13px !important;
    }}
    /* 구분선 */
    hr {{ border-color: rgba(0,0,0,0.07) !important; }}
    /* 섹션 헤더 */
    h4 {{ color: {COLOR_TEXT} !important; font-size: 15px !important; font-weight: 600 !important; }}
    /* info/warning 박스 색상 */
    div[data-testid="stAlert"] {{ border-radius: 8px !important; }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div style='background:{COLOR_DARK}; padding:18px 24px; border-radius:12px; margin-bottom:16px; display:flex; align-items:center; justify-content:space-between;'>
    <div>
        <h1 style='color:#ffffff; margin:0; font-size:20px; font-weight:600; letter-spacing:-0.02em;'>
            네이버 검색 트렌드 대시보드
        </h1>
        <p style='color:rgba(255,255,255,0.4); margin:4px 0 0 0; font-size:11px;'>
            네이버 데이터랩 API 기반 · 마케팅 키워드 트렌드 분석 · Python · Streamlit · Plotly
        </p>
    </div>
    <div style='background:{COLOR_PRIMARY}; color:#fff; font-size:10px; padding:4px 12px; border-radius:20px; font-weight:500;'>
        마케팅 분석 도구
    </div>
</div>
""", unsafe_allow_html=True)


# ============================
# 상단 필터 바 (사이드바 대체)
# ============================

col_f1, col_f2, col_f3, col_f4, col_f5, col_f6, col_f7, col_f8 = st.columns([2.5, 1.5, 1.5, 1.5, 1.5, 1.5, 2, 1])
with col_f1:
    keyword_input = st.text_input("키워드 (쉼표로 구분)", placeholder="키워드를 입력해주세요.")
with col_f2:
    start_date = st.date_input("시작 날짜")
with col_f3:
    end_date = st.date_input("종료 날짜")
with col_f4:
    time_unit = st.selectbox(
        "조회 단위",
        options=["date", "week", "month"],
        format_func=lambda x: {"date": "일별", "week": "주별", "month": "월별"}[x]
    )
with col_f5:
    device_option = st.radio(
        "기기", options=["", "pc", "mo"],
        format_func=lambda x: {"": "전체", "pc": "PC", "mo": "모바일"}[x],
        horizontal=True
    )
with col_f6:
    gender_option = st.radio(
        "성별", options=["", "m", "f"],
        format_func=lambda x: {"": "전체", "m": "남성", "f": "여성"}[x],
        horizontal=True
    )
with col_f7:
    age_options = st.multiselect(
        "연령",
        options=["1", "2", "3", "4", "5", "6"],
        format_func=lambda x: {"1": "10대", "2": "20대", "3": "30대", "4": "40대", "5": "50대", "6": "60대 이상"}[x],
        default=[]
    )
with col_f8:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    run = st.button("조회", use_container_width=True)
    if "df" in st.session_state:
        df_side = st.session_state["df"]
        start_date_side = st.session_state["start_date"]
        end_date_side = st.session_state["end_date"]
        csv = df_side.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="CSV",
            data=csv,
            file_name=f"naver_trend_{start_date_side}_{end_date_side}.csv",
            mime="text/csv",
            use_container_width=True
        )

st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)


# ============================
# 데이터 조회
# ============================

if run and keyword_input:
    keywords = [kw.strip() for kw in keyword_input.split(",")]
    raw_data = get_trend_data(
        keywords,
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d"),
        time_unit,
        gender=gender_option,
        ages=age_options,
        device=device_option
    )
    df = parse_trend_data(raw_data)
    st.session_state["df"] = df
    st.session_state["keywords"] = keywords
    st.session_state["start_date"] = start_date
    st.session_state["end_date"] = end_date
    st.session_state["time_unit"] = time_unit
    st.session_state["gender"] = gender_option
    st.session_state["ages"] = age_options
    st.session_state["device"] = device_option
    # 새 조회 시 타겟 분석 결과 초기화
    for key in ["df_pc", "df_mobile", "df_gender_m", "df_gender_f", "df_ages"]:
        if key in st.session_state:
            del st.session_state[key]


# ============================
# 메인 렌더링
# ============================

if "df" in st.session_state:
    df = st.session_state["df"]
    keywords = st.session_state["keywords"]
    start_date = st.session_state["start_date"]
    end_date = st.session_state["end_date"]
    time_unit = st.session_state["time_unit"]
    gender = st.session_state.get("gender", "")
    ages = st.session_state.get("ages", [])
    device = st.session_state.get("device", "")

    tab1, tab2, tab3 = st.tabs(["트렌드 분석", "이벤트 분석", "데이터 해석 가이드"])


    # ============================
    # TAB 1: 트렌드 분석
    # 순서: 상단KPI → 추이그래프 → 타겟분석(PC/성별/연령) → 하단KPI → 메모
    # ============================

    with tab1:

        # --- 상단 KPI 카드 ---
        current_insights_kpi, past_insights_kpi = get_insight(df, period_unit=time_unit)
        surge_count = sum(1 for _, _, _, level in current_insights_kpi if level in ["폭발", "유입"])
        avg_by_keyword = df.groupby("키워드")["검색량"].mean()
        top_keyword = avg_by_keyword.idxmax()
        trend_types = [item[5] for item in past_insights_kpi if len(item) >= 6]
        main_trend = trend_types[0] if trend_types else "—"
        analysis_days = (end_date - start_date).days

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("급등 감지 키워드", f"{surge_count}개")
        col2.metric("최고 상승 키워드", top_keyword)
        col3.metric("주요 트렌드 유형", main_trend)
        col4.metric("분석 기간", f"{analysis_days}일")

        st.markdown("<br>", unsafe_allow_html=True)

        # --- 추이 그래프 ---
        memo_dict = load_memo()
        fig = go.Figure()
        for i, kw in enumerate(keywords):
            kw_df = df[df["키워드"] == kw]
            fig.add_trace(go.Scatter(
                x=kw_df["날짜"], y=kw_df["검색량"], name=kw,
                mode="lines+markers",
                line=dict(color=CHART_COLORS[i % len(CHART_COLORS)], width=2.5),
                marker=dict(size=5),
                hovertemplate=f"<b>{kw}</b><br>날짜: %{{x|%Y년 %m월 %d일}}<br>검색량: %{{y:.1f}}<extra></extra>"
            ))
            current_insights_temp, past_insights_temp = get_insight(df[df["키워드"] == kw].copy(), period_unit=time_unit)
            peak_dates = []
            for item in past_insights_temp:
                date_match = re.search(r'(\d+)월\s*(\d+)일', item[2])
                if date_match:
                    month = int(date_match.group(1))
                    day = int(date_match.group(2))
                    year = pd.Timestamp.now().year
                    peak_dates.append(pd.Timestamp(year=year, month=month, day=day))
            if peak_dates:
                peak_df = kw_df[kw_df["날짜"].isin(peak_dates)]
                hover_texts = []
                for d in peak_df["날짜"]:
                    date_str = d.strftime("%Y-%m-%d")
                    memo = memo_dict.get(kw, {}).get(date_str, "")
                    hover_texts.append(
                        f"📌 {kw} ({date_str})<br>메모: {memo}" if memo
                        else f"📌 {kw} ({date_str})<br>메모 없음"
                    )
                fig.add_trace(go.Scatter(
                    x=peak_df["날짜"], y=peak_df["검색량"], mode="markers",
                    name=f"{kw} 급등 감지",
                    marker=dict(symbol="star", size=14, color="#EF4444", line=dict(color="#ffffff", width=1)),
                    text=hover_texts, hovertemplate="%{text}<extra></extra>"
                ))

        fig.update_layout(
            title=dict(text="키워드별 검색량 추이", font=dict(size=15, color=COLOR_TEXT)),
            plot_bgcolor=COLOR_CARD, paper_bgcolor=COLOR_CARD, font=dict(color=COLOR_TEXT, size=12),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
            hovermode="x unified",
            xaxis=dict(showgrid=True, gridcolor="#F3F4F6", tickfont=dict(size=11)),
            yaxis=dict(showgrid=True, gridcolor="#F3F4F6", title="검색량 (상대값)", tickfont=dict(size=11)),
            margin=dict(l=0, r=0, t=50, b=0), height=380
        )
        st.plotly_chart(fig, use_container_width=True, key="main_chart")

        # --- 타겟 분석 섹션 (추이 그래프 바로 아래) ---
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"<h4 style='color:{COLOR_TEXT};'>타겟 분석</h4>", unsafe_allow_html=True)
        st.markdown(f"<hr style='border:1px solid #E5E7EB; margin:4px 0 12px 0;'>", unsafe_allow_html=True)

        st.caption("PC / 성별 / 연령 비교 분석은 API를 총 8회 추가 호출합니다.")
        if st.button("PC / 성별 / 연령 비교 분석 실행", use_container_width=False):
            with st.spinner("데이터 불러오는 중... (API 8회 호출)"):
                # PC vs 모바일 (2회)
                raw_pc = get_trend_data(keywords, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), time_unit, gender=gender, ages=ages, device="pc")
                raw_mobile = get_trend_data(keywords, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), time_unit, gender=gender, ages=ages, device="mo")
                st.session_state["df_pc"] = parse_trend_data(raw_pc)
                st.session_state["df_mobile"] = parse_trend_data(raw_mobile)
                # 성별 (2회)
                raw_male = get_trend_data(keywords, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), time_unit, gender="m", ages=ages, device=device)
                raw_female = get_trend_data(keywords, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), time_unit, gender="f", ages=ages, device=device)
                st.session_state["df_gender_m"] = parse_trend_data(raw_male)
                st.session_state["df_gender_f"] = parse_trend_data(raw_female)
                # 연령 (6회)
                age_code_map = {"1": "10대", "2": "20대", "3": "30대", "4": "40대", "5": "50대", "6": "60대+"}
                df_ages_dict = {}
                for code, label in age_code_map.items():
                    raw_age = get_trend_data(keywords, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"), time_unit, gender=gender, ages=[code], device=device)
                    df_ages_dict[label] = parse_trend_data(raw_age)
                st.session_state["df_ages"] = df_ages_dict

        # 타겟 분석 결과 표시
        if "df_pc" in st.session_state and "df_gender_m" in st.session_state:
            df_pc = st.session_state["df_pc"]
            df_mobile = st.session_state["df_mobile"]
            df_gender_m = st.session_state["df_gender_m"]
            df_gender_f = st.session_state["df_gender_f"]
            df_ages_dict = st.session_state["df_ages"]

            # PC vs 모바일 | 성별 비교 (2열)
            col_t1, col_t2 = st.columns(2)

            with col_t1:
                st.markdown(f"<p style='color:{COLOR_SUB}; font-size:15px; font-weight:600; margin:8px 0 6px 0;'>PC vs 모바일</p>", unsafe_allow_html=True)
                pc_avgs = [round(df_pc[df_pc["키워드"] == kw]["검색량"].mean() if kw in df_pc["키워드"].values else 0, 1) for kw in keywords]
                mobile_avgs = [round(df_mobile[df_mobile["키워드"] == kw]["검색량"].mean() if kw in df_mobile["키워드"].values else 0, 1) for kw in keywords]
                fig_device = go.Figure()
                fig_device.add_trace(go.Bar(name="PC", x=keywords, y=pc_avgs, marker_color=COLOR_PRIMARY, text=pc_avgs, textposition="outside"))
                fig_device.add_trace(go.Bar(name="모바일", x=keywords, y=mobile_avgs, marker_color=COLOR_SECONDARY, text=mobile_avgs, textposition="outside"))
                fig_device.update_layout(
                    barmode="group", plot_bgcolor=COLOR_CARD, paper_bgcolor=COLOR_CARD,
                    font=dict(color=COLOR_TEXT),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    xaxis=dict(tickfont=dict(size=13)),
                    yaxis=dict(title="평균 검색량"),
                    bargap=0.3, bargroupgap=0.1,
                    margin=dict(l=20, r=20, t=40, b=0), height=300
                )
                st.plotly_chart(fig_device, use_container_width=True, key="device_chart")

            with col_t2:
                st.markdown(f"<p style='color:{COLOR_SUB}; font-size:15px; font-weight:600; margin:8px 0 6px 0;'>성별 비교</p>", unsafe_allow_html=True)
                male_avgs = [round(df_gender_m[df_gender_m["키워드"] == kw]["검색량"].mean() if kw in df_gender_m["키워드"].values else 0, 1) for kw in keywords]
                female_avgs = [round(df_gender_f[df_gender_f["키워드"] == kw]["검색량"].mean() if kw in df_gender_f["키워드"].values else 0, 1) for kw in keywords]
                fig_gender = go.Figure()
                fig_gender.add_trace(go.Bar(name="남성", x=keywords, y=male_avgs, marker_color="#3A9080", text=male_avgs, textposition="outside"))
                fig_gender.add_trace(go.Bar(name="여성", x=keywords, y=female_avgs, marker_color=COLOR_SECONDARY, text=female_avgs, textposition="outside"))
                fig_gender.update_layout(
                    barmode="group", plot_bgcolor=COLOR_CARD, paper_bgcolor=COLOR_CARD,
                    font=dict(color=COLOR_TEXT),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    xaxis=dict(tickfont=dict(size=13)),
                    yaxis=dict(title="평균 검색량"),
                    bargap=0.3, bargroupgap=0.1,
                    margin=dict(l=20, r=20, t=40, b=0), height=300
                )
                st.plotly_chart(fig_gender, use_container_width=True, key="gender_chart")

            # 연령 분포 (전체 너비)
            st.markdown(f"<p style='color:{COLOR_SUB}; font-size:15px; font-weight:600; margin:12px 0 6px 0;'>연령별 검색 분포</p>", unsafe_allow_html=True)
            age_labels = list(df_ages_dict.keys())

            # 연령대별 색상 계열 (진한→중간→밝은 순 / 키워드 수에 맞게 인덱싱)
            # 핑크·블루 제외, 무지개 느낌 없이 채도 낮춰 세련되게
            AGE_COLOR_GROUPS = {
                "10대":  ["#2D7A6E", "#3A9080", "#4BAF9F"],
                "20대":  ["#2D7A6E", "#3A9080", "#4BAF9F"],
                "30대":  ["#2D7A6E", "#3A9080", "#4BAF9F"],
                "40대":  ["#2D7A6E", "#3A9080", "#4BAF9F"],
                "50대":  ["#2D7A6E", "#3A9080", "#4BAF9F"],
                "60대+": ["#2D7A6E", "#3A9080", "#4BAF9F"],
            }

            fig_age = go.Figure()
            for i, kw in enumerate(keywords):
                # 각 연령대 색 계열에서 키워드 순서(i)에 맞는 밝기 선택
                colors_for_kw = [
                    AGE_COLOR_GROUPS.get(lbl, ["#8B5CF6", "#C4B5FD", "#DDD6FE"])[i % 3]
                    for lbl in age_labels
                ]
                age_avgs = [
                    round(df_ages_dict[lbl][df_ages_dict[lbl]["키워드"] == kw]["검색량"].mean()
                          if kw in df_ages_dict[lbl]["키워드"].values else 0, 1)
                    for lbl in age_labels
                ]
                fig_age.add_trace(go.Bar(
                    name=kw, x=age_labels, y=age_avgs,
                    marker_color=colors_for_kw,
                    text=age_avgs, textposition="outside"
                ))
            fig_age.update_layout(
                barmode="group", plot_bgcolor=COLOR_CARD, paper_bgcolor=COLOR_CARD,
                font=dict(color=COLOR_TEXT),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                xaxis=dict(tickfont=dict(size=13)),
                yaxis=dict(title="평균 검색량"),
                bargap=0.2, bargroupgap=0.1,
                margin=dict(l=20, r=20, t=40, b=0), height=300
            )
            st.plotly_chart(fig_age, use_container_width=True, key="age_chart")

            # 타겟 해석 문장
            interpretations = generate_target_interpretation(keywords, df_pc, df_mobile, gender, ages, device)
            if interpretations:
                st.markdown(f"<p style='color:{COLOR_SUB}; font-size:15px; font-weight:600; margin:8px 0 6px 0;'>타겟 해석</p>", unsafe_allow_html=True)
                for kw, interp in interpretations:
                    st.markdown(f"""
                    <div style='background-color:{COLOR_CARD}; padding:10px 16px; border-radius:8px;
                         border-left:4px solid {COLOR_PRIMARY}; margin-bottom:6px; border: 0.5px solid rgba(0,0,0,0.07);'>
                        <span style='color:{COLOR_TEXT}; font-size:15px;'><b>{kw}</b> &nbsp; {interp}</span>
                    </div>
                    """, unsafe_allow_html=True)

        # --- 하단 KPI 카드 ---
        st.markdown("<br>", unsafe_allow_html=True)
        max_z_kw, max_z_val, max_z_date_str, surge_total = "—", 0, "—", 0
        for item in past_insights_kpi:
            date_match = re.search(r'(\d+)월\s*(\d+)일', item[2])
            z_match = re.search(r'z=([\d.]+)', item[2])
            if z_match:
                z_val = float(z_match.group(1))
                if z_val > max_z_val:
                    max_z_val = z_val
                    max_z_kw = item[1]
                    if date_match:
                        max_z_date_str = f"{date_match.group(1)}/{date_match.group(2)}"
            if item[3] in ["폭발", "유입"]:
                surge_total += 1

        latest = df.groupby("키워드").apply(
            lambda x: x.sort_values("날짜").tail(2)["검색량"].pct_change().iloc[-1] * 100
        )
        top_rise = latest.max()
        top_rise_kw = latest.idxmax()

        col_a1, col_a2, col_a3, col_a4 = st.columns(4)
        col_a1.metric("최고 z-score", f"{max_z_val:.1f}" if max_z_val > 0 else "—", max_z_kw)
        col_a2.metric("최근 상승률", f"{top_rise:.1f}%", top_rise_kw)
        col_a3.metric("급등 발생일", max_z_date_str)
        col_a4.metric("급등 감지 횟수", f"{surge_total}회")

        # --- 키워드 비교 분석 테이블 ---
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"<h4 style='color:{COLOR_TEXT};'>키워드 비교 분석</h4>", unsafe_allow_html=True)
        st.markdown(f"<hr style='border:1px solid #E5E7EB; margin:4px 0 8px 0;'>", unsafe_allow_html=True)
        summary = df.groupby("키워드")["검색량"].agg(["mean", "max", "min"]).reset_index()
        summary.columns = ["키워드", "평균 검색량", "최고 검색량", "최저 검색량"]
        summary["순서"] = summary["키워드"].apply(lambda x: keywords.index(x) if x in keywords else 999)
        summary = summary.sort_values("순서").drop(columns=["순서"]).reset_index(drop=True)
        summary["평균 검색량"] = summary["평균 검색량"].round(1)
        html_table_kw = f"""
        <style>
        .custom-table {{ width:100%; border-collapse:collapse; font-size:15px; color:{COLOR_TEXT}; background-color:{COLOR_CARD}; border-radius:10px; overflow:hidden; border: 0.5px solid rgba(0,0,0,0.08); }}
        .custom-table th {{ background-color:{COLOR_PRIMARY}; color:#ffffff; padding:12px 16px; text-align:left; font-size:24px; font-weight:600; }}
        .custom-table td {{ padding:12px 16px; border-bottom:1px solid #F3F4F6; font-size:24px; }}
        .custom-table tr:last-child td {{ border-bottom:none; }}
        .custom-table tr:hover td {{ background-color:{COLOR_BG}; }}
        </style>
        <table class='custom-table'>
            <tr><th>키워드</th><th>평균 검색량</th><th>최고 검색량</th><th>최저 검색량</th></tr>
        """
        for _, row in summary.iterrows():
            html_table_kw += f"<tr><td>{row['키워드']}</td><td>{row['평균 검색량']}</td><td>{row['최고 검색량']}</td><td>{row['최저 검색량']:.1f}</td></tr>"
        html_table_kw += "</table>"
        st.markdown(html_table_kw, unsafe_allow_html=True)

        # --- 메모 섹션 ---
        st.markdown("<br>", unsafe_allow_html=True)
        memo_dict = load_memo()
        st.markdown(f"<h4 style='color:{COLOR_TEXT};'>피크 원인 메모</h4>", unsafe_allow_html=True)
        st.markdown(f"<hr style='border:1px solid #E5E7EB; margin:4px 0 8px 0;'>", unsafe_allow_html=True)

        current_insights_all, past_insights_all = get_insight(df, period_unit=time_unit)
        peak_options = []
        for item in past_insights_all:
            date_match = re.search(r'(\d+)월\s*(\d+)일', item[2])
            if date_match:
                month = int(date_match.group(1))
                day = int(date_match.group(2))
                year = pd.Timestamp.now().year
                peak_date = pd.Timestamp(year=year, month=month, day=day)
                peak_options.append((item[1], peak_date.strftime("%Y-%m-%d"), item[2]))

        if peak_options:
            col_memo1, col_memo2 = st.columns([1, 2])
            with col_memo1:
                peak_labels = [f"{kw} — {date} ({msg[:15]}...)" for kw, date, msg in peak_options]
                selected_idx = st.selectbox("급등 날짜 선택", range(len(peak_labels)), format_func=lambda x: peak_labels[x])
                selected_kw = peak_options[selected_idx][0]
                selected_date = peak_options[selected_idx][1]
            with col_memo2:
                existing_memo = memo_dict.get(selected_kw, {}).get(selected_date, "")
                memo_input = st.text_input("원인 메모 입력", value=existing_memo, placeholder="메모를 입력하여 주시기 바랍니다.")
                if st.button("메모 저장"):
                    if selected_kw not in memo_dict:
                        memo_dict[selected_kw] = {}
                    memo_dict[selected_kw][selected_date] = memo_input
                    save_memo(memo_dict)
                    st.success(f"✅ '{selected_kw}' {selected_date} 메모가 저장됐습니다.")
                    st.rerun()
        else:
            st.markdown("<p style='color:#9CA3AF; font-size:14px;'>급등 이벤트가 감지된 날짜가 없습니다.</p>", unsafe_allow_html=True)

        # 이벤트 로그 테이블
        log_rows = []
        for kw_name, dates in memo_dict.items():
            for date_str, memo in dates.items():
                log_rows.append({"키워드": kw_name, "날짜": date_str, "메모": memo})

        if log_rows:
            st.markdown(f"<h4 style='color:{COLOR_TEXT}; margin-top:20px;'>이벤트 분석 로그</h4>", unsafe_allow_html=True)
            st.markdown(f"<hr style='border:1px solid #E5E7EB; margin:4px 0 8px 0;'>", unsafe_allow_html=True)
            col_h1, col_h2, col_h3, col_h4 = st.columns([1.5, 1.5, 4, 0.5])
            with col_h1: st.markdown(f"<p style='color:{COLOR_PRIMARY}; font-weight:600; font-size:14px; margin:0;'>키워드</p>", unsafe_allow_html=True)
            with col_h2: st.markdown(f"<p style='color:{COLOR_PRIMARY}; font-weight:600; font-size:14px; margin:0;'>날짜</p>", unsafe_allow_html=True)
            with col_h3: st.markdown(f"<p style='color:{COLOR_PRIMARY}; font-weight:600; font-size:14px; margin:0;'>메모</p>", unsafe_allow_html=True)
            with col_h4: st.markdown(f"<p style='color:{COLOR_PRIMARY}; font-weight:600; font-size:14px; margin:0;'>삭제</p>", unsafe_allow_html=True)
            st.markdown(f"<hr style='border:1px solid #E5E7EB; margin:4px 0 4px 0;'>", unsafe_allow_html=True)
            sorted_rows = sorted(log_rows, key=lambda x: x["날짜"], reverse=True)
            for row in sorted_rows:
                col_r1, col_r2, col_r3, col_r4 = st.columns([1.5, 1.5, 4, 0.5])
                with col_r1: st.markdown(f"<p style='font-size:14px; margin:4px 0;'>{row['키워드']}</p>", unsafe_allow_html=True)
                with col_r2: st.markdown(f"<p style='font-size:14px; margin:4px 0;'>{row['날짜']}</p>", unsafe_allow_html=True)
                with col_r3: st.markdown(f"<p style='font-size:14px; margin:4px 0;'>{row['메모']}</p>", unsafe_allow_html=True)
                with col_r4:
                    if st.button("🗑", key=f"del_{row['키워드']}_{row['날짜']}"):
                        del memo_dict[row["키워드"]][row["날짜"]]
                        if not memo_dict[row["키워드"]]:
                            del memo_dict[row["키워드"]]
                        save_memo(memo_dict)
                        st.rerun()
            log_df = pd.DataFrame(sorted_rows)
            log_csv = log_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="이벤트 로그 CSV 다운로드",
                data=log_csv,
                file_name="event_log.csv",
                mime="text/csv"
            )


    # ============================
    # TAB 2: 이벤트 분석
    # 순서: 현재상태 → 기간내이벤트 → 키워드비교테이블
    # ============================

    with tab2:
        current_insights, past_insights = get_insight(df, period_unit=time_unit)

        # --- 현재 상태 ---
        st.markdown(f"<h4 style='color:{COLOR_TEXT}; margin-top:8px;'>현재 상태</h4>", unsafe_allow_html=True)
        st.markdown(f"<hr style='border:1px solid #E5E7EB; margin:4px 0 8px 0;'>", unsafe_allow_html=True)

        if gender or ages or device:
            age_label_map = {"1": "10대", "2": "20대", "3": "30대", "4": "40대", "5": "50대", "6": "60대이상"}
            st.info(f"""
            💡 **타겟 필터 적용 중** \n
            {'성별: ' + {'m':'남성','f':'여성'}.get(gender,'') if gender else ''} {'/ 연령: ' + '/'.join([age_label_map[a] for a in ages]) if ages else ''} {'/ 기기: ' + {'pc':'PC','mo':'모바일'}.get(device,'') if device else ''} 기준 데이터입니다.
            필터 적용 시 데이터 수가 줄어 z-score 신뢰도가 낮아질 수 있습니다.
            """)

        for emoji, kw, msg, level in current_insights:
            if level == "폭발":
                bg_color, border_color = "#DDF0EC", COLOR_PRIMARY
                action_texts = ["· 실시간 SNS 소재 제작 즉각 검토", "· 검색광고 입찰 경쟁도 점검", "· 관련 키워드 확장 여부 확인"]
            elif level == "유입":
                bg_color, border_color = "#EEF9F7", COLOR_PRIMARY
                action_texts = ["· VIEW탭/블로그 콘텐츠 선점 검토", "· 모바일 랜딩 최적화 점검", "· SEO 키워드 콘텐츠 축적 시작"]
            else:
                bg_color, border_color = COLOR_CARD, "#D1D5DB"
                action_texts = []

            st.markdown(f"""
            <div style='background-color:{bg_color}; padding:10px 16px; border-radius:8px;
            border-left:4px solid {border_color}; margin-bottom:6px; border: 0.5px solid rgba(0,0,0,0.07);'>
            <span style='color:{COLOR_TEXT}; font-size:20px;'>{emoji} <b>{kw}</b> &nbsp; {msg}</span>
            </div>
            """, unsafe_allow_html=True)

            if level in ["폭발", "유입"]:
                news_url = f"https://search.naver.com/search.naver?ssc=tab.news.all&query={kw}&sm=tab_opt&nso=so%3Ar%2Cp%3A1w"
                blog_url = f"https://search.naver.com/search.naver?ssc=tab.blog.all&query={kw}&sm=tab_opt&nso=so%3Ar%2Cp%3A1w"
                shopping_url = f"https://search.shopping.naver.com/search/all?query={kw}&sort=rel"
                st.markdown(f"<p style='color:{COLOR_SUB}; font-size:15px; font-weight:600; margin:8px 0 6px 0;'>원인 탐색</p>", unsafe_allow_html=True)
                col_a, col_b, col_c = st.columns([1, 1, 1])
                with col_a: st.link_button("뉴스 확인", news_url)
                with col_b: st.link_button("블로그 확인", blog_url)
                with col_c: st.link_button("쇼핑 확인", shopping_url)
                actions_html = "".join([f"<p style='color:#374151; font-size:14px; margin:4px 0;'>{a}</p>" for a in action_texts])
                st.markdown(f"<p style='color:{COLOR_SUB}; font-size:15px; font-weight:600; margin:12px 0 6px 0;'>추천 마케팅 액션</p>{actions_html}", unsafe_allow_html=True)

        # --- 기간 내 주요 이벤트 ---
        if past_insights:
            st.markdown(f"<h4 style='color:{COLOR_TEXT}; margin-top:24px;'>기간 내 주요 이벤트</h4>", unsafe_allow_html=True)
            st.markdown(f"<hr style='border:1px solid #E5E7EB; margin:4px 0 8px 0;'>", unsafe_allow_html=True)
            for emoji, kw, msg, level, type_emoji, type_name, interpret, actions in past_insights:
                bg_color, border_color = "#DDF0EC", COLOR_PRIMARY

                date_match = re.search(r'(\d+)월\s*(\d+)일', msg)
                if date_match:
                    month, day = int(date_match.group(1)), int(date_match.group(2))
                    year = pd.Timestamp.now().year
                    peak_date = pd.Timestamp(year=year, month=month, day=day)
                    ds = (peak_date - pd.Timedelta(days=1)).strftime("%Y.%m.%d")
                    de = (peak_date + pd.Timedelta(days=1)).strftime("%Y.%m.%d")
                    ds_clean, de_clean = ds.replace(".", ""), de.replace(".", "")
                    news_url = f"https://search.naver.com/search.naver?ssc=tab.news.all&query={kw}&sm=tab_opt&nso=so%3Ar%2Cp%3Afrom{ds_clean}to{de_clean}"
                    blog_url = f"https://search.naver.com/search.naver?ssc=tab.blog.all&query={kw}&sm=tab_opt&nso=so%3Ar%2Cp%3Afrom{ds_clean}to{de_clean}"
                else:
                    news_url, blog_url = "", ""

                st.markdown(f"""
                <div style='background-color:{bg_color}; padding:10px 16px; border-radius:8px;
                border-left:4px solid {border_color}; margin-bottom:6px;'>
                <span style='color:{COLOR_TEXT}; font-size:20px;'>{emoji} <b>{kw}</b> &nbsp; {msg}</span>
                </div>
                """, unsafe_allow_html=True)

                actions_html = "".join([f"<p style='color:#374151; font-size:14px; margin:4px 0;'>· {a}</p>" for a in actions])
                st.markdown(f"""
                <p style='color:{COLOR_SUB}; font-size:15px; margin:8px 0 4px 0; font-weight:600;'>트렌드 유형: {type_name}</p>
                <p style='color:{COLOR_TEXT}; font-size:14px; margin:0 0 10px 0;'>{interpret}</p>
                <p style='color:{COLOR_SUB}; font-size:15px; margin:0 0 6px 0; font-weight:600;'>당시 원인 추적</p>
                """, unsafe_allow_html=True)

                if news_url:
                    col_a, col_b, col_c = st.columns([1, 1, 4])
                    with col_a: st.link_button("전후 뉴스 확인", news_url)
                    with col_b: st.link_button("당시 블로그 반응 확인", blog_url)

                st.markdown(f"<p style='color:{COLOR_SUB}; font-size:15px; margin:12px 0 6px 0; font-weight:600;'>마케터 액션 제안</p>{actions_html}", unsafe_allow_html=True)


    # ============================
    # TAB 3: 데이터 해석 가이드 (기존 tab2 그대로)
    # ============================

    with tab3:
        st.markdown(f"""
        <div style='background:{COLOR_DARK}; padding:14px 20px; border-radius:10px; margin-bottom:16px;'>
            <p style='color:{COLOR_PRIMARY}; font-size:14px; font-weight:600; margin:0;'>
                이 대시보드는 "평소 대비 얼마나 비정상적으로 관심이 증가했는지"를 탐지하는 데 초점을 맞추고 있습니다.
            </p>
            <p style='color:rgba(255,255,255,0.45); font-size:11px; margin:6px 0 0 0;'>
                네이버 데이터랩 API 기반 · 통계적 이상치 감지 · 마케팅 의사결정 보조 도구
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(f"<h4 style='color:{COLOR_TEXT}; margin-top:8px;'>검색량 해석 기준</h4>", unsafe_allow_html=True)
        st.markdown(f"<hr style='border:1px solid #E5E7EB; margin:4px 0 12px 0;'>", unsafe_allow_html=True)

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown(f"""
            <div style='background-color:{COLOR_CARD}; padding:16px; border-radius:10px; border:0.5px solid rgba(0,0,0,0.08);'>
                <p style='color:{COLOR_TEXT}; font-weight:700; margin:0 0 8px 0;'>검색량 수치의 의미</p>
                <table style='width:100%; border-collapse:collapse; font-size:14px;'>
                    <tr style='background-color:{COLOR_PRIMARY};'><th style='padding:8px; text-align:left; color:#fff;'>수치</th><th style='padding:8px; text-align:left; color:#fff;'>의미</th></tr>
                    <tr><td style='padding:8px;'>100</td><td style='padding:8px;'>조회 기간 내 최고 검색량 (절대값 아님)</td></tr>
                    <tr style='background-color:{COLOR_BG};'><td style='padding:8px;'>50</td><td style='padding:8px;'>최고점 대비 절반 수준</td></tr>
                    <tr><td style='padding:8px;'>0에 가까움</td><td style='padding:8px;'>해당 기간 내 거의 검색되지 않음</td></tr>
                </table>
            </div>
            """, unsafe_allow_html=True)
        with col_t2:
            st.markdown(f"""
            <div style='background-color:{COLOR_CARD}; padding:16px; border-radius:10px; border:0.5px solid rgba(0,0,0,0.08);'>
                <p style='color:{COLOR_TEXT}; font-weight:700; margin:0 0 8px 0;'>z-score 해석 기준</p>
                <table style='width:100%; border-collapse:collapse; font-size:14px;'>
                    <tr style='background-color:{COLOR_PRIMARY};'><th style='padding:8px; text-align:left; color:#fff;'>z값</th><th style='padding:8px; text-align:left; color:#fff;'>의미</th></tr>
                    <tr><td style='padding:8px;'>z ≥ 2.5</td><td style='padding:8px;'>이례적 급등 (상위 0.6% 수준)</td></tr>
                    <tr style='background-color:{COLOR_BG};'><td style='padding:8px;'>z ≥ 1.5</td><td style='padding:8px;'>유의미한 관심 증가 (상위 7% 수준)</td></tr>
                    <tr><td style='padding:8px;'>z &lt; 1.5</td><td style='padding:8px;'>평소 변동 범위 내 안정</td></tr>
                </table>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        with st.expander("z-score란 무엇인가요?"):
            st.markdown("""
            **z-score**는 현재 검색량이 평소 패턴에서 얼마나 벗어났는지를 수치로 나타냅니다.

            단순 상승률 대신 z-score를 쓰는 이유는 **요일 효과(주말/평일 편차)** 와 **기저효과(지난주가 유독 낮았던 경우)** 같은 노이즈를 제거하기 위해서입니다.

            또한 이 대시보드는 **현재 검색량을 평균 계산에서 제외(shift(1) 적용)** 하여, 급등한 오늘 값이 평균을 끌어올려 급등이 희석되는 문제를 방지했습니다.
            """)

        with st.expander("폭발 / 유입 / 안정 판단 기준이 무엇인가요?"):
            st.markdown("""
            **트렌드 대폭발 (z ≥ 2.5, 최근 2일 이상 지속)**
            통계적으로 상위 0.6% 수준의 이례적인 급등입니다. 즉각적인 마케팅 대응이 필요한 수준입니다.

            **관심 유입 (z ≥ 1.5, 최근 2일 이상 지속)**
            상위 7% 수준의 유의미한 관심 증가입니다. 콘텐츠 선점 기회를 검토할 시점입니다.

            **안정**
            평소 변동 범위 내에서 움직이는 안정적인 상태입니다.

            ⚠️ 단, 하루만 반짝 급등한 경우는 노이즈로 보고 걸러냅니다. (지속성 필터: 최근 7일 중 2일 이상)
            """)

        with st.expander("왜 월별 조회에서는 급등 분석이 제한되나요?"):
            st.markdown("""
            월별 데이터는 데이터 포인트 수가 너무 적습니다.

            예를 들어 6개월 조회 시 데이터가 6개뿐인데, 여기서 3개월 이동평균을 계산하면 유효한 z-score가 3개밖에 나오지 않아 통계적 신뢰도가 매우 낮아집니다.

            따라서 월별 조회는 **장기 흐름 파악용**으로만 활용하고, 정확한 급등 분석은 **일별(최소 14일) 또는 주별(최소 12주)** 로 조회하는 것을 권장합니다.
            """)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown(f"<h4 style='color:{COLOR_TEXT};'>트렌드 유형별 의미</h4>", unsafe_allow_html=True)
        st.markdown(f"<hr style='border:1px solid #E5E7EB; margin:4px 0 12px 0;'>", unsafe_allow_html=True)

        col_c1, col_c2, col_c3, col_c4 = st.columns(4)
        with col_c1:
            st.markdown(f"""
            <div style='background-color:{COLOR_CARD}; padding:16px; border-radius:10px; border-top:4px solid {COLOR_PRIMARY}; border:0.5px solid rgba(0,0,0,0.08);'>
                <p style='font-size:20px; margin:0;'>단기 이슈형</p>
                <p style='color:{COLOR_SUB}; font-size:12px; margin:8px 0;'>급등 후 3일 내 빠르게 감소. 이벤트/바이럴 가능성.</p>
                <p style='color:{COLOR_SUB}; font-size:11px; font-weight:600; margin:8px 0 4px 0;'>추천 액션</p>
                <p style='color:{COLOR_TEXT}; font-size:12px; margin:2px 0;'>· 실시간 SNS 단타 대응</p>
                <p style='color:{COLOR_TEXT}; font-size:12px; margin:2px 0;'>· 이슈 재발 대비 플랜 준비</p>
            </div>
            """, unsafe_allow_html=True)
        with col_c2:
            st.markdown(f"""
            <div style='background-color:{COLOR_CARD}; padding:16px; border-radius:10px; border-top:4px solid {COLOR_PRIMARY}; border:0.5px solid rgba(0,0,0,0.08);'>
                <p style='font-size:20px; margin:0;'>지속성 상승형</p>
                <p style='color:{COLOR_SUB}; font-size:12px; margin:8px 0;'>급등 후 60% 이상 검색량 유지. 관심 확장 가능성.</p>
                <p style='color:{COLOR_SUB}; font-size:11px; font-weight:600; margin:8px 0 4px 0;'>추천 액션</p>
                <p style='color:{COLOR_TEXT}; font-size:12px; margin:2px 0;'>· SEO 콘텐츠 선점</p>
                <p style='color:{COLOR_TEXT}; font-size:12px; margin:2px 0;'>· 검색광고 예산 상향</p>
            </div>
            """, unsafe_allow_html=True)
        with col_c3:
            st.markdown(f"""
            <div style='background-color:{COLOR_CARD}; padding:16px; border-radius:10px; border-top:4px solid {COLOR_PRIMARY}; border:0.5px solid rgba(0,0,0,0.08);'>
                <p style='font-size:20px; margin:0;'>반복 패턴형</p>
                <p style='color:{COLOR_SUB}; font-size:12px; margin:8px 0;'>7일 이상 간격으로 피크 2회 이상. 시즌성 가능성.</p>
                <p style='color:{COLOR_SUB}; font-size:11px; font-weight:600; margin:8px 0 4px 0;'>추천 액션</p>
                <p style='color:{COLOR_TEXT}; font-size:12px; margin:2px 0;'>· 피크 2주 전 선제 콘텐츠</p>
                <p style='color:{COLOR_TEXT}; font-size:12px; margin:2px 0;'>· 경쟁사 패턴 모니터링</p>
            </div>
            """, unsafe_allow_html=True)
        with col_c4:
            st.markdown(f"""
            <div style='background-color:{COLOR_CARD}; padding:16px; border-radius:10px; border-top:4px solid {COLOR_PRIMARY}; border:0.5px solid rgba(0,0,0,0.08);'>
                <p style='font-size:20px; margin:0;'>안정형</p>
                <p style='color:{COLOR_SUB}; font-size:12px; margin:8px 0;'>특이 급등 없이 검색량 유지. 기반 키워드.</p>
                <p style='color:{COLOR_SUB}; font-size:11px; font-weight:600; margin:8px 0 4px 0;'>추천 액션</p>
                <p style='color:{COLOR_TEXT}; font-size:12px; margin:2px 0;'>· 상시 브랜딩 유지</p>
                <p style='color:{COLOR_TEXT}; font-size:12px; margin:2px 0;'>· 유입 효율 모니터링</p>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.warning("""
        ⚠️ 데이터 한계 (Data Limitation)

        1. 검색량은 절대값이 아닌 상대값(0~100)입니다. 카테고리가 다른 키워드를 1:1로 비교하면 왜곡이 생길 수 있습니다.
        2. 검색 의도를 구분하지 않습니다. 급등이 긍정적 화제인지 부정적 이슈인지는 뉴스/블로그 교차 검증이 필요합니다.
        3. 검색량이 극히 적은 키워드는 z-score 왜곡이 생길 수 있습니다.
        4. 네이버 내부 알고리즘 변화에 영향을 받을 수 있습니다.
        """)

        st.markdown("<br>", unsafe_allow_html=True)
        col_u1, col_u2 = st.columns(2)
        with col_u1:
            st.markdown(f"""
            <div style='background-color:{COLOR_CARD}; padding:16px; border-radius:10px; border:0.5px solid rgba(0,0,0,0.08); border-left:4px solid {COLOR_PRIMARY};'>
                <p style='color:{COLOR_PRIMARY}; font-weight:700; margin:0 0 8px 0;'>활용하기 좋은 상황</p>
                <p style='color:{COLOR_TEXT}; font-size:14px; margin:3px 0;'>· 특정 이슈 이후 검색 반응 확인</p>
                <p style='color:{COLOR_TEXT}; font-size:14px; margin:3px 0;'>· 브랜드/경쟁사 관심도 변화 탐색</p>
                <p style='color:{COLOR_TEXT}; font-size:14px; margin:3px 0;'>· 콘텐츠/광고 반응 모니터링</p>
                <p style='color:{COLOR_TEXT}; font-size:14px; margin:3px 0;'>· 시즌성 키워드 탐색</p>
            </div>
            """, unsafe_allow_html=True)
        with col_u2:
            st.markdown(f"""
            <div style='background-color:{COLOR_CARD}; padding:16px; border-radius:10px; border:0.5px solid rgba(0,0,0,0.08); border-left:4px solid #9CA3AF;'>
                <p style='color:{COLOR_SUB}; font-weight:700; margin:0 0 8px 0;'>주의가 필요한 상황</p>
                <p style='color:{COLOR_TEXT}; font-size:14px; margin:3px 0;'>· 실제 매출 추정에 활용</p>
                <p style='color:{COLOR_TEXT}; font-size:14px; margin:3px 0;'>· 시장 점유율 비교</p>
                <p style='color:{COLOR_TEXT}; font-size:14px; margin:3px 0;'>· 절대 트래픽 해석</p>
                <p style='color:{COLOR_TEXT}; font-size:14px; margin:3px 0;'>· 카테고리 다른 키워드 1:1 비교</p>
            </div>
            """, unsafe_allow_html=True)