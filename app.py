import streamlit as st
import pandas as pd
import numpy as np
import random
import calendar
import sqlite3
import json
import time
from datetime import date, timedelta

st.set_page_config(page_title="GA 월간 근무 스케줄", layout="wide")

st.markdown("""
<style>
.stApp { background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%); }
.main-title { font-size: 34px; font-weight: 800; color: #1e293b; }
.sub-title { font-size: 16px; color: #64748b; margin-bottom: 25px; }
.section-title { font-size: 22px; font-weight: 700; color: #334155; margin-top: 18px; margin-bottom: 10px; }
.store-badge { display: inline-block; background: #4f46e5; color: white; padding: 7px 14px; border-radius: 999px; font-weight: 700; }
div[data-testid="stMetric"] { background: white; padding: 18px; border-radius: 16px; box-shadow: 0 3px 10px rgba(15,23,42,0.08); }
div[data-testid="stMetric"] label { color: #334155 !important; }
div[data-testid="stMetric"] div[data-testid="stMetricValue"] { color: #1e293b !important; }
.stCaption, .stCaption p { color: #334155 !important; }
/* 탭 글씨 */
button[data-baseweb="tab"] p { color: #334155 !important; }
button[data-baseweb="tab"][aria-selected="true"] p { color: #1e293b !important; font-weight: 700 !important; }
/* expander 제목 */
details summary p { color: #334155 !important; }
.streamlit-expanderHeader p { color: #334155 !important; }
</style>
""", unsafe_allow_html=True)

SHIFTS = ["오픈", "마감"]
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# ─────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────

def get_conn():
    return sqlite3.connect("schedule.db")

def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT UNIQUE,
                password TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT,
                name TEXT,
                employee_type TEXT,
                monthly_off_count INTEGER,
                max_work INTEGER,
                available_days TEXT,
                available_shifts TEXT,
                day_off_requests TEXT,
                hourly_wage INTEGER DEFAULT 0,
                monthly_salary INTEGER DEFAULT 0,
                open_hours REAL DEFAULT 8.0,
                close_hours REAL DEFAULT 8.0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS substitute_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT,
                original_emp TEXT,
                request_date TEXT,
                shift TEXT,
                status TEXT DEFAULT '대기중',
                matched_emp TEXT DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
    # 기존 DB 마이그레이션
    with get_conn() as conn:
        for col, default in [
            ("hourly_wage", "0"), ("monthly_salary", "0"),
            ("open_hours", "8.0"), ("close_hours", "8.0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE employees ADD COLUMN {col} REAL DEFAULT {default}")
            except:
                pass


def insert_sample_data():
    """샘플 매장 + 직원 10명 자동 삽입 (이미 있으면 스킵)"""
    with get_conn() as conn:
        if conn.execute("SELECT id FROM stores WHERE store_name=?", ("삼성라이온즈",)).fetchone():
            return
        conn.execute("INSERT INTO stores (store_name, password) VALUES (?, ?)", ("삼성라이온즈", "1234"))
        sample = [
            ("김민준","월급제",8,26,["월","화","수","목","금","토","일"],["오픈","마감"],[],0,2800000,8.0,8.0),
            ("이서연","월급제",8,26,["월","화","수","목","금","토","일"],["오픈","마감"],[],0,2600000,8.0,8.0),
            ("강현우","월급제",8,26,["월","화","수","목","금","토","일"],["오픈","마감"],[],0,2500000,8.0,8.0),
            ("박지훈","시급제",-1,20,["월","화","수","목","금"],["오픈"],[],10030,0,8.0,0.0),
            ("최수아","시급제",-1,18,["화","수","목","금","토"],["오픈","마감"],[],10030,0,8.0,8.0),
            ("정도윤","시급제",-1,16,["월","수","금","토","일"],["마감"],[],10030,0,0.0,8.0),
            ("한예진","시급제",-1,14,["토","일"],["오픈","마감"],[],10030,0,8.0,8.0),
            ("오태양","시급제",-1,20,["월","화","목","금","토"],["오픈","마감"],[],10030,0,8.0,8.0),
            ("임나은","시급제",-1,12,["수","목","금","토","일"],["오픈"],[],10030,0,8.0,0.0),
            ("윤소희","시급제",-1,16,["월","화","수","금","토"],["오픈","마감"],[],10030,0,8.0,8.0),
        ]
        for s in sample:
            conn.execute("""
                INSERT INTO employees
                (store_name,name,employee_type,monthly_off_count,max_work,
                 available_days,available_shifts,day_off_requests,
                 hourly_wage,monthly_salary,open_hours,close_hours)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, ("삼성라이온즈", s[0], s[1], s[2], s[3],
                  json.dumps(s[4], ensure_ascii=False),
                  json.dumps(s[5], ensure_ascii=False),
                  json.dumps(s[6]),
                  s[7], s[8], s[9], s[10]))

def register_store(store_name, password):
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO stores (store_name, password) VALUES (?,?)", (store_name, password))
        return True
    except Exception:
        return False

def login_store(store_name, password):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM stores WHERE store_name=? AND password=?", (store_name, password)
        ).fetchone()
    return row is not None

def _row_to_emp(row):
    return {
        "id": row[0],
        "이름": row[2],
        "직원유형": row[3],
        "월휴무개수": None if row[4] == -1 else row[4],
        "월최대근무횟수": row[5],
        "출근가능요일": json.loads(row[6]),
        "가능근무": json.loads(row[7]),
        "휴무요청": [date.fromisoformat(d) for d in json.loads(row[8])],
        "시급": row[9] if len(row) > 9 else 0,
        "월급": row[10] if len(row) > 10 else 0,
        "오픈시간": row[11] if len(row) > 11 else 8.0,
        "마감시간": row[12] if len(row) > 12 else 8.0,
    }

def load_employees(store_name):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM employees WHERE store_name=?", (store_name,)).fetchall()
    return [_row_to_emp(r) for r in rows]

def _emp_params(store_name, emp):
    return (
        store_name,
        emp["이름"], emp["직원유형"],
        -1 if emp["월휴무개수"] is None else emp["월휴무개수"],
        emp["월최대근무횟수"],
        json.dumps(emp["출근가능요일"], ensure_ascii=False),
        json.dumps(emp["가능근무"], ensure_ascii=False),
        json.dumps([d.isoformat() for d in emp["휴무요청"]], ensure_ascii=False),
        emp.get("시급", 0),
        emp.get("월급", 0),
        emp.get("오픈시간", 8.0),
        emp.get("마감시간", 8.0),
    )

def save_employee(store_name, emp):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO employees (store_name,name,employee_type,monthly_off_count,max_work,"
            "available_days,available_shifts,day_off_requests,hourly_wage,monthly_salary,open_hours,close_hours)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            _emp_params(store_name, emp),
        )

def update_employee(emp_id, emp):
    with get_conn() as conn:
        conn.execute(
            "UPDATE employees SET name=?,employee_type=?,monthly_off_count=?,max_work=?,"
            "available_days=?,available_shifts=?,day_off_requests=?,"
            "hourly_wage=?,monthly_salary=?,open_hours=?,close_hours=? WHERE id=?",
            _emp_params("", emp)[1:] + (emp_id,),
        )

def delete_employee(emp_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM employees WHERE id=?", (emp_id,))

def clear_employees(store_name):
    with get_conn() as conn:
        conn.execute("DELETE FROM employees WHERE store_name=?", (store_name,))

# ─────────────────────────────────────────────
# 로그인
# ─────────────────────────────────────────────

init_db()
insert_sample_data()

if "login" not in st.session_state:
    st.session_state.login = False
if "store_name" not in st.session_state:
    st.session_state.store_name = None

if not st.session_state.login:
    st.markdown('<div class="main-title">GA 기반 월간 근무 스케줄 자동 생성 시스템</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">매장별 직원 정보를 저장하고 유전 알고리즘으로 월간 근무표를 생성합니다.</div>', unsafe_allow_html=True)

    tab_login, tab_reg = st.tabs(["매장 로그인", "매장 등록"])

    with tab_login:
        sn = st.text_input("매장명")
        pw = st.text_input("비밀번호", type="password")
        if st.button("로그인", use_container_width=True):
            if login_store(sn, pw):
                st.session_state.login = True
                st.session_state.store_name = sn
                st.session_state.employees = load_employees(sn)
                st.rerun()
            else:
                st.error("매장명 또는 비밀번호가 틀렸습니다.")

    with tab_reg:
        new_sn = st.text_input("새 매장명")
        new_pw = st.text_input("새 비밀번호", type="password")
        if st.button("매장 등록", use_container_width=True):
            if new_sn and new_pw:
                st.success("등록 완료") if register_store(new_sn, new_pw) else st.error("이미 등록된 매장입니다.")
            else:
                st.warning("매장명과 비밀번호를 입력해주세요.")
    st.stop()

# ─────────────────────────────────────────────
# 메인 헤더
# ─────────────────────────────────────────────

st.markdown('<div class="main-title">GA 기반 월간 근무 스케줄 자동 생성 시스템</div>', unsafe_allow_html=True)
st.markdown(f'<span class="store-badge">현재 매장: {st.session_state.store_name}</span>', unsafe_allow_html=True)

if st.button("로그아웃"):
    st.session_state.login = False
    st.session_state.store_name = None
    st.rerun()

if "employees" not in st.session_state:
    st.session_state.employees = load_employees(st.session_state.store_name)

# ─────────────────────────────────────────────
# 1. 월 설정
# ─────────────────────────────────────────────

st.markdown('<div class="section-title">1. 스케줄 생성 월 설정</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    st.markdown('<p style="color:#334155; font-size:14px; margin-bottom:4px;">년도</p>', unsafe_allow_html=True)
    year = st.number_input("년도", 2024, 2030, 2026, label_visibility="collapsed")
with col2:
    st.markdown('<p style="color:#334155; font-size:14px; margin-bottom:4px;">월</p>', unsafe_allow_html=True)
    month = st.number_input("월", 1, 12, 5, label_visibility="collapsed")

last_day = calendar.monthrange(year, month)[1]
dates = [date(year, month, d) for d in range(1, last_day + 1)]

def weekday_str(d): return WEEKDAYS[d.weekday()]

# ─────────────────────────────────────────────
# 사이드바 – 직원 등록/수정
# ─────────────────────────────────────────────

st.sidebar.header("직원 등록 / 수정")

employees = st.session_state.employees
options   = ["신규 직원"] + [e["이름"] for e in employees]
sel_name  = st.sidebar.selectbox("직원 등록 내역 불러오기", options)
sel_emp   = next((e for e in employees if e["이름"] == sel_name), None)

def _default(key, fallback):
    return sel_emp[key] if sel_emp else fallback

name      = st.sidebar.text_input("직원 이름", value=_default("이름", ""))
emp_type  = st.sidebar.selectbox("직원 유형", ["시급제", "월급제"],
                                  index=["시급제", "월급제"].index(_default("직원유형", "시급제")))
avail_shifts = st.sidebar.multiselect("가능 근무", SHIFTS, default=_default("가능근무", SHIFTS))

if emp_type == "시급제":
    avail_days = st.sidebar.multiselect("출근 가능 요일", WEEKDAYS, default=_default("출근가능요일", WEEKDAYS))
    monthly_off = None
    hourly_wage = st.sidebar.number_input("시급 (원)", min_value=0, value=int(_default("시급", 10030)), step=100)
    monthly_sal = 0
    open_hours  = st.sidebar.number_input("오픈 근무시간 (시간)", 0.0, 24.0, float(_default("오픈시간", 8.0)), step=0.5)
    close_hours = st.sidebar.number_input("마감 근무시간 (시간)", 0.0, 24.0, float(_default("마감시간", 8.0)), step=0.5)
else:
    avail_days  = WEEKDAYS
    monthly_off = st.sidebar.number_input("월 휴무 개수", 0, 15,
                                           int(_default("월휴무개수", 8) or 8))
    monthly_sal = st.sidebar.number_input("월급 (원)", min_value=0, value=int(_default("월급", 2500000)), step=10000)
    hourly_wage = 0
    open_hours  = 8.0
    close_hours = 8.0

max_work = st.sidebar.slider("월 최대 근무 횟수", 1, 31, int(_default("월최대근무횟수", 22)))

# 달력형 휴무 요청 선택
def calendar_dayoff_selector(dates, year, month, key_prefix, default_selected=None):
    default_selected = default_selected or []
    st.sidebar.markdown("### 휴무 요청일 선택")
    first_weekday, _ = calendar.monthrange(year, month)
    selected = []

    for wd in WEEKDAYS:
        pass  # header
    header_cols = st.sidebar.columns(7)
    for i, wd in enumerate(WEEKDAYS):
        header_cols[i].markdown(f"**{wd}**")

    week = [None] * first_weekday
    for d in dates:
        week.append(d)
        if len(week) == 7:
            cols = st.sidebar.columns(7)
            for i, day in enumerate(week):
                if day:
                    if cols[i].checkbox(str(day.day), value=day in default_selected,
                                        key=f"{key_prefix}_{day.isoformat()}"):
                        selected.append(day)
            week = []
    if week:
        week += [None] * (7 - len(week))
        cols = st.sidebar.columns(7)
        for i, day in enumerate(week):
            if day:
                if cols[i].checkbox(str(day.day), value=day in default_selected,
                                    key=f"{key_prefix}_{day.isoformat()}"):
                    selected.append(day)
    return selected

sel_day_off = calendar_dayoff_selector(
    dates, year, month,
    key_prefix=f"dayoff_{sel_name}_{name}",
    default_selected=_default("휴무요청", [])
)

new_emp = {
    "이름": name, "직원유형": emp_type,
    "월휴무개수": monthly_off, "월최대근무횟수": max_work,
    "출근가능요일": avail_days, "가능근무": avail_shifts,
    "휴무요청": sel_day_off,
    "시급": hourly_wage, "월급": monthly_sal,
    "오픈시간": open_hours, "마감시간": close_hours,
}

if st.sidebar.button("직원 추가", use_container_width=True):
    if name:
        save_employee(st.session_state.store_name, new_emp)
        st.session_state.employees = load_employees(st.session_state.store_name)
        st.rerun()
    else:
        st.sidebar.warning("직원 이름을 입력해주세요.")

if st.sidebar.button("직원 정보 수정", use_container_width=True):
    if sel_emp:
        update_employee(sel_emp["id"], new_emp)
        st.session_state.employees = load_employees(st.session_state.store_name)
        st.rerun()
    else:
        st.sidebar.warning("수정할 직원을 선택해주세요.")

if st.sidebar.button("직원 삭제", use_container_width=True):
    if sel_emp:
        delete_employee(sel_emp["id"])
        st.session_state.employees = load_employees(st.session_state.store_name)
        st.rerun()
    else:
        st.sidebar.warning("삭제할 직원을 선택해주세요.")

# ─────────────────────────────────────────────
# 2. 등록된 직원 목록
# ─────────────────────────────────────────────

st.markdown('<div class="section-title">2. 등록된 직원</div>', unsafe_allow_html=True)

employees = st.session_state.employees
if not employees:
    st.warning("왼쪽 사이드바에서 직원을 먼저 등록해주세요.")
    st.stop()

show_df = pd.DataFrame(employees).drop(columns=["id"])
show_df["출근가능요일"] = show_df["출근가능요일"].apply(", ".join)
show_df["가능근무"]     = show_df["가능근무"].apply(", ".join)
show_df["휴무요청"]     = show_df["휴무요청"].apply(lambda x: ", ".join(d.strftime("%m/%d") for d in x))
st.dataframe(show_df, use_container_width=True)

if st.button("현재 매장 직원 전체 초기화"):
    clear_employees(st.session_state.store_name)
    st.session_state.employees = []
    st.rerun()

# ─────────────────────────────────────────────
# 3. 필요 인원 설정
# ─────────────────────────────────────────────

st.markdown('<div class="section-title">3. 필요 인원 설정</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)
open_required  = col1.number_input("오픈 필요 인원", 1, 20, 2)
close_required = col2.number_input("마감 필요 인원", 1, 20, 2)
generations    = col3.slider("GA 반복 세대 수", 30, 300, 120)

required_staff = {"오픈": open_required, "마감": close_required}

# ─────────────────────────────────────────────
# GA 로직
# ─────────────────────────────────────────────

emp_by_name: dict = {}

def build_emp_index():
    global emp_by_name
    emp_by_name = {e["이름"]: e for e in employees}

def get_target_work(emp):
    if emp["직원유형"] == "월급제":
        return last_day - emp["월휴무개수"]
    return emp["월최대근무횟수"]

def is_available(emp, work_date, shift):
    if work_date in emp["휴무요청"]:
        return False
    if shift not in emp["가능근무"]:
        return False
    if emp["직원유형"] == "시급제" and weekday_str(work_date) not in emp["출근가능요일"]:
        return False
    return True

def empty_schedule():
    return {d: {s: [] for s in SHIFTS} for d in dates}

def calc_wc(schedule):
    """날짜 기준 근무일수 (같은 날 오픈+마감 = 1일)"""
    wc = {e["이름"]: 0 for e in employees}
    for d in dates:
        worked = {name for s in SHIFTS for name in schedule[d][s]}
        for name in worked:
            wc[name] += 1
    return wc

def work_count(schedule, name):
    return sum(1 for d in dates if any(name in schedule[d][s] for s in SHIFTS))

def _available_days(emp):
    """해당 직원이 배정 가능한 날짜 집합 (휴무요청 제외, 시급제는 요일 필터)"""
    result = set()
    for d in dates:
        if d in emp["휴무요청"]:
            continue
        if emp["직원유형"] == "시급제" and weekday_str(d) not in emp["출근가능요일"]:
            continue
        result.add(d)
    return result

def consecutive_count(schedule, name, up_to_date):
    """up_to_date 이전까지 연속 근무일수 (당일 포함 안 함)"""
    idx = dates.index(up_to_date)
    count = 0
    for i in range(idx - 1, -1, -1):
        if any(name in schedule[dates[i]][s] for s in SHIFTS):
            count += 1
        else:
            break
    return count

def would_exceed_5(schedule, name, d):
    """d에 배정하면 연속 5일 초과 여부"""
    before = consecutive_count(schedule, name, d)
    if before >= 5:
        return True
    # d 이후 연속일 확인
    idx = dates.index(d)
    after = 0
    for i in range(idx + 1, len(dates)):
        if any(name in schedule[dates[i]][s] for s in SHIFTS):
            after += 1
        else:
            break
    return (before + 1 + after) > 5

def build_schedule_from_scratch():
    """
    월급제 직원을 먼저 목표 근무일수만큼 배정한 뒤,
    시급제 직원으로 나머지 슬롯을 채우는 2-패스 방식.
    연속 5일 초과 금지를 하드 제약으로 적용.
    """
    schedule = empty_schedule()
    wc = {e["이름"]: 0 for e in employees}

    # ── 패스 1: 월급제 직원 목표 근무일수 배정 ──────────────────────────
    monthly_emps = [e for e in employees if e["직원유형"] == "월급제"]
    for emp in monthly_emps:
        target = get_target_work(emp)
        name   = emp["이름"]
        avail  = sorted(_available_days(emp))
        # 연속 5일 제약을 고려해 그리디하게 배정
        work_days = []
        avail_shuffled = avail[:]
        random.shuffle(avail_shuffled)
        for d in avail_shuffled:
            if len(work_days) >= target:
                break
            if not would_exceed_5(schedule, name, d):
                work_days.append(d)
                avail_shifts = [s for s in SHIFTS if s in emp["가능근무"]]
                if avail_shifts:
                    s = random.choice(avail_shifts)
                    schedule[d][s].append(name)
                    wc[name] += 1
        # 연속제약 때문에 target 미달 시 제약 완화해서 채움
        if wc[name] < target:
            remaining = [d for d in avail if not any(name in schedule[d][sx] for sx in SHIFTS)]
            random.shuffle(remaining)
            for d in remaining:
                if wc[name] >= target:
                    break
                avail_shifts = [s for s in SHIFTS if s in emp["가능근무"]]
                if avail_shifts:
                    s = random.choice(avail_shifts)
                    schedule[d][s].append(name)
                    wc[name] += 1

    # ── 패스 2: 빈 슬롯을 시급제/부족한 월급제로 채우기 ─────────────────
    slots = [(d, s) for d in dates for s in SHIFTS]
    random.shuffle(slots)
    for d, s in slots:
        while len(schedule[d][s]) < required_staff[s]:
            candidates = [
                e for e in employees
                if is_available(e, d, s)
                and not any(e["이름"] in schedule[d][sx] for sx in SHIFTS)
                and wc[e["이름"]] < get_target_work(e)
                and not would_exceed_5(schedule, e["이름"], d)
            ]
            if not candidates:
                break
            random.shuffle(candidates)
            chosen = candidates[0]
            schedule[d][s].append(chosen["이름"])
            wc[chosen["이름"]] += 1

    return schedule

def consecutive_run_length(schedule, name, d):
    """날짜 d를 포함하는 연속 근무 블록의 길이"""
    idx = dates.index(d)
    start = idx
    while start > 0 and any(name in schedule[dates[start-1]][s] for s in SHIFTS):
        start -= 1
    end = idx
    while end < len(dates)-1 and any(name in schedule[dates[end+1]][s] for s in SHIFTS):
        end += 1
    return end - start + 1

def repair_schedule(schedule):
    """
    1단계 — 하드 제약 위반 제거 (휴무요청/불가시프트)
    2단계 — 연속 5일 초과 위반 제거 (뒤쪽 날짜부터 제거해 앞쪽 보존)
    3단계 — 날짜 기준 wc 집계 후 근무일수 초과분 제거
    4단계 — 월급제 목표 미달 직원 우선 강제 보충
    5단계 — 나머지 슬롯 부족 보충
    """
    lookup = emp_by_name if emp_by_name else {e["이름"]: e for e in employees}

    # 1단계: 하드 제약 위반 제거
    for d in dates:
        for s in SHIFTS:
            schedule[d][s] = [
                name for name in schedule[d][s]
                if is_available(lookup[name], d, s)
            ]

    # 2단계: 연속 5일 초과 제거 — 역순으로 돌며 블록이 5 초과인 직원 제거
    for d in reversed(dates):
        for s in SHIFTS:
            kept = []
            for name in schedule[d][s]:
                if consecutive_run_length(schedule, name, d) > 5:
                    pass  # 제거 (뒤쪽 날짜부터 걷어냄)
                else:
                    kept.append(name)
            schedule[d][s] = kept

    # 3단계: 날짜 기준 wc 집계 후 근무일수 초과분 제거
    wc = calc_wc(schedule)
    for d in reversed(dates):
        for s in SHIFTS:
            kept = []
            for name in schedule[d][s]:
                if wc[name] > get_target_work(lookup[name]):
                    other = any(name in schedule[d][sx] for sx in SHIFTS if sx != s)
                    if not other:
                        wc[name] -= 1
                else:
                    kept.append(name)
            schedule[d][s] = kept

    # 4단계: 월급제 목표 미달 직원 우선 강제 보충 (연속 5일 제약 준수)
    monthly_short = [
        e for e in employees
        if e["직원유형"] == "월급제" and wc[e["이름"]] < get_target_work(e)
    ]
    for emp in monthly_short:
        name   = emp["이름"]
        target = get_target_work(emp)
        day_list = list(dates)
        random.shuffle(day_list)
        for d in day_list:
            if wc[name] >= target:
                break
            if any(name in schedule[d][sx] for sx in SHIFTS):
                continue
            if would_exceed_5(schedule, name, d):
                continue
            avail_shifts = [s for s in SHIFTS if is_available(emp, d, s)]
            if avail_shifts:
                s = random.choice(avail_shifts)
                schedule[d][s].append(name)
                wc[name] += 1
        # 연속 제약으로 여전히 미달이면 제약 완화 (목표 달성 우선)
        if wc[name] < target:
            for d in dates:
                if wc[name] >= target:
                    break
                if any(name in schedule[d][sx] for sx in SHIFTS):
                    continue
                avail_shifts = [s for s in SHIFTS if is_available(emp, d, s)]
                if avail_shifts:
                    s = random.choice(avail_shifts)
                    schedule[d][s].append(name)
                    wc[name] += 1

    # 5단계: 나머지 슬롯 부족 보충 (연속 5일 제약 준수)
    slots = [(d, s) for d in dates for s in SHIFTS]
    random.shuffle(slots)
    for d, s in slots:
        while len(schedule[d][s]) < required_staff[s]:
            candidates = [
                e for e in employees
                if is_available(e, d, s)
                and not any(e["이름"] in schedule[d][sx] for sx in SHIFTS)
                and wc[e["이름"]] < get_target_work(e)
                and not would_exceed_5(schedule, e["이름"], d)
            ]
            if not candidates:
                break
            random.shuffle(candidates)
            chosen = candidates[0]["이름"]
            schedule[d][s].append(chosen)
            wc[chosen] += 1

    return schedule

def max_consecutive(schedule, name):
    work_set = {d for d in dates if any(name in schedule[d][s] for s in SHIFTS)}
    max_c = cur = 0
    for d in dates:
        cur = cur + 1 if d in work_set else 0
        if cur > max_c:
            max_c = cur
    return max_c

_fitness_base: float = 0.0   # run_ga 시작 시 한 번만 계산

def fitness(schedule):
    score = _fitness_base
    wc = calc_wc(schedule)

    # 인원 부족/초과
    for d in dates:
        for s in SHIFTS:
            diff = len(schedule[d][s]) - required_staff[s]
            if diff < 0:
                score -= abs(diff) * 1000
            elif diff > 0:
                score -= diff * 100

    # 마감 → 다음날 오픈
    for i in range(len(dates) - 1):
        closing = set(schedule[dates[i]]["마감"])
        opening = set(schedule[dates[i + 1]]["오픈"])
        score -= len(closing & opening) * 800

    # 시급제 초과 근무
    for emp in employees:
        if emp["직원유형"] == "시급제":
            over = wc[emp["이름"]] - get_target_work(emp)
            if over > 0:
                score -= over * 500



    # 시급제 근무 분산
    part_time_wc = [wc[e["이름"]] for e in employees if e["직원유형"] == "시급제"]
    if len(part_time_wc) > 1:
        mean = sum(part_time_wc) / len(part_time_wc)
        std  = (sum((v - mean) ** 2 for v in part_time_wc) / len(part_time_wc)) ** 0.5
        score -= std * 30

    # 인건비 최적화: 총 예상 인건비가 높을수록 감점
    # 인건비 페널티 가중치는 다른 제약 대비 낮게 설정 (스케줄 품질 우선)
    total_labor = 0
    for emp in employees:
        name = emp["이름"]
        if emp["직원유형"] == "시급제":
            hourly     = emp.get("시급", 0)
            open_cnt   = sum(1 for d in dates if name in schedule[d]["오픈"])
            close_cnt  = sum(1 for d in dates if name in schedule[d]["마감"])
            total_h    = open_cnt * emp.get("오픈시간", 8.0) + close_cnt * emp.get("마감시간", 8.0)
            weekly_avg = total_h / (last_day / 7)
            juhu       = int(hourly * 8) if weekly_avg >= 15 else 0
            total_labor += int(hourly * total_h) + juhu
        else:
            total_labor += emp.get("월급", 0)

    # 인건비 정규화: 직원 평균 시급 기준으로 스케일 조정
    avg_hourly = sum(e.get("시급", 0) for e in employees if e["직원유형"] == "시급제")
    n_part = max(sum(1 for e in employees if e["직원유형"] == "시급제"), 1)
    avg_hourly /= n_part
    labor_penalty_weight = 0.001  # 인건비 1원당 0.001점 감점 (스케줄 품질 대비 낮은 가중치)
    score -= total_labor * labor_penalty_weight

    return score

def crossover(p1, p2):
    child = empty_schedule()
    for d in dates:
        for s in SHIFTS:
            child[d][s] = (p1[d][s] if random.random() < 0.5 else p2[d][s])[:]
    return repair_schedule(child)

def mutate(schedule, rate=0.05):
    for d in dates:
        for s in SHIFTS:
            if random.random() < rate:
                schedule[d][s] = []
    return repair_schedule(schedule)

def run_ga(on_progress=None):
    global _fitness_base
    build_emp_index()

    # base를 한 번만 계산해서 캐싱
    n_emps  = max(len(employees), 1)
    max_req = max(required_staff.values())

    # 최대 가능 인건비 (모든 직원이 최대 근무 시)
    max_labor = sum(
        (e.get("시급", 0) * e.get("월최대근무횟수", 26) * max(e.get("오픈시간", 8.0), e.get("마감시간", 8.0))
         + e.get("시급", 0) * 8)  # 주휴수당 포함
        if e["직원유형"] == "시급제"
        else e.get("월급", 0)
        for e in employees
    )

    _fitness_base = (
        last_day * len(SHIFTS) * max_req * 1000
        + (last_day - 1) * n_emps * 800
        + n_emps * last_day * 500
        + last_day * 30
        + max_labor * 0.001  # 인건비 페널티 상한 보정
    )

    pop_size   = 20
    elite_size = 5
    population = [repair_schedule(build_schedule_from_scratch()) for _ in range(pop_size)]

    # (점수, 스케줄) 쌍 유지 — 엘리트는 점수 재사용으로 속도 확보
    scored = [(fitness(ind), ind) for ind in population]
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    start = time.time()

    # 0세대 기록 (초반 급등 구간 확인용)
    history_best = [scored[0][0]]
    history_avg  = [sum(s for s, _ in scored) / len(scored)]

    for gen in range(generations):
        top_pool = [ind for _, ind in scored[:10]]
        elites   = scored[:elite_size]          # 점수 재사용

        children = []
        while len(children) < pop_size - elite_size:
            p1, p2 = random.sample(top_pool, 2)
            children.append(mutate(crossover(p1, p2)))

        # 자식만 새로 계산, 엘리트는 재사용
        scored = elites + [(fitness(c), c) for c in children]
        scored.sort(key=lambda x: x[0], reverse=True)

        if scored[0][0] > best_score:
            best_score, best = scored[0]

        history_best.append(scored[0][0])
        history_avg.append(sum(s for s, _ in scored) / len(scored))

        if on_progress:
            on_progress(gen + 1, generations, time.time() - start, best_score)

    return best, best_score, history_best, history_avg

# ─────────────────────────────────────────────
# 4. 스케줄 생성 & 결과 출력
# ─────────────────────────────────────────────

if st.button("GA로 월간 스케줄 생성", type="primary", use_container_width=True):
    prog_bar  = st.progress(0)
    stat_text = st.empty()

    def on_progress(gen, total, elapsed, best_score):
        ratio    = gen / total
        avg_sec  = elapsed / gen
        remaining = avg_sec * (total - gen)
        prog_bar.progress(ratio)
        stat_text.markdown(
            f"**세대 {gen} / {total}** &nbsp;|&nbsp; "
            f"경과 {elapsed:.1f}s &nbsp;|&nbsp; "
            f"예상 남은 시간 **{remaining:.1f}s** &nbsp;|&nbsp; "
            f"현재 최고 점수 {best_score:,.0f}"
        )

    best_schedule, best_score, history_best, history_avg = run_ga(on_progress=on_progress)
    prog_bar.progress(1.0)
    stat_text.markdown(f'<p style="color:#166534; background:#dcfce7; padding:12px 16px; border-radius:8px; font-weight:600;">완료! 총 소요 시간 및 최종 적합도 점수: {round(best_score, 2)}</p>', unsafe_allow_html=True)

    # 마커 함수
    emp_type_map = {e["이름"]: e["직원유형"] for e in employees}
    def name_with_marker(name):
        return f"{name}{'★' if emp_type_map.get(name) == '월급제' else '◆'}"

    # ── 요약 지표 (항상 상단 노출) ──────────────────────────────────────
    # 분석 데이터 미리 계산
    analysis = []
    for emp in employees:
        name = emp["이름"]
        wc   = work_count(best_schedule, name)
        mc   = max_consecutive(best_schedule, name)
        open_cnt = close_cnt = c2o = 0
        for i, d in enumerate(dates):
            if name in best_schedule[d]["오픈"]: open_cnt += 1
            if name in best_schedule[d]["마감"]: close_cnt += 1
            if i < len(dates)-1 and name in best_schedule[d]["마감"] and name in best_schedule[dates[i+1]]["오픈"]:
                c2o += 1
        target = get_target_work(emp)
        analysis.append({
            "직원": name, "유형": emp["직원유형"],
            "목표근무일수": target, "실제근무일수": wc,
            "목표휴무일수": last_day - target, "실제휴무일수": last_day - wc,
            "오픈횟수": open_cnt, "마감횟수": close_cnt,
            "최대연속근무": mc, "마감→다음날오픈": c2o,
        })
    analysis_df = pd.DataFrame(analysis)

    detail = []
    for d in dates:
        detail.append({
            "날짜": d.strftime("%m/%d"), "요일": weekday_str(d),
            "오픈": ", ".join(name_with_marker(n) for n in best_schedule[d]["오픈"]) or "없음",
            "마감": ", ".join(name_with_marker(n) for n in best_schedule[d]["마감"]) or "없음",
            "오픈 부족": max(0, open_required  - len(best_schedule[d]["오픈"])),
            "마감 부족": max(0, close_required - len(best_schedule[d]["마감"])),
        })
    result_df = pd.DataFrame(detail)

    total_shortage = int(result_df["오픈 부족"].sum() + result_df["마감 부족"].sum())
    col1, col2, col3 = st.columns(3)
    col1.metric("총 부족 인원",          total_shortage)
    col2.metric("마감→다음날 오픈",       int(analysis_df["마감→다음날오픈"].sum()))
    col3.metric("5일 초과 연속근무 직원", int((analysis_df["최대연속근무"] > 5).sum()))

    st.markdown('<p style="color:#166534; background:#dcfce7; padding:12px 16px; border-radius:8px; font-weight:600;">월간 스케줄 생성이 완료되었습니다.</p>', unsafe_allow_html=True)

    # ── GA 수렴 그래프 ────────────────────────────────────────────────────
    with st.expander("📈 GA 수렴 그래프", expanded=True):
        import altair as alt

        n_emps  = max(len(employees), 1)
        max_req = max(required_staff.values())
        base_score = (
            last_day * len(SHIFTS) * max_req * 1000
            + (last_day - 1) * n_emps * 800
            + n_emps * last_day * 500
            + last_day * 30
        )

        # y축 하한: 전체 점수 중 최솟값의 95% (변화가 잘 보이도록)
        y_min = min(min(history_best), min(history_avg)) * 0.995
        y_max = base_score * 1.005

        gens = list(range(len(history_best)))
        chart_df = pd.DataFrame({
            "세대":      gens + gens + gens,
            "점수":      history_best + history_avg + [base_score] * len(gens),
            "구분":      ["최고 점수"] * len(gens)
                        + ["평균 점수"] * len(gens)
                        + ["이론상 최고점"] * len(gens),
        })

        color_scale = alt.Scale(
            domain=["최고 점수", "평균 점수", "이론상 최고점"],
            range=["#6c63ff", "#a78bfa", "#00d4aa"],
        )
        stroke_dash = alt.condition(
            alt.datum["구분"] == "이론상 최고점",
            alt.value([4, 4]),
            alt.value([0]),
        )

        chart = (
            alt.Chart(chart_df)
            .mark_line(point=False)
            .encode(
                x=alt.X("세대:Q", title="세대"),
                y=alt.Y("점수:Q", title="적합도 점수",
                        scale=alt.Scale(domain=[y_min, y_max])),
                color=alt.Color("구분:N", scale=color_scale,
                                legend=alt.Legend(orient="top")),
                strokeDash=stroke_dash,
                tooltip=["세대:Q", "구분:N",
                         alt.Tooltip("점수:Q", format=",")],
            )
            .properties(height=320)
            .interactive()
        )
        st.altair_chart(chart, use_container_width=True)

        col_a, col_b, col_c, col_d = st.columns(4)
        col_a.metric("초기 점수",  f"{history_best[0]:,.0f}")
        col_b.metric("최종 점수",  f"{history_best[-1]:,.0f}")
        col_c.metric("개선",       f"+{history_best[-1]-history_best[0]:,.0f}")
        improve_pct = (history_best[-1] - history_best[0]) / max(abs(history_best[0]), 1) * 100
        col_d.metric("개선율",     f"{improve_pct:.1f}%")

    # ── 4. 월간 캘린더 ───────────────────────────────────────────────────
    st.markdown('<div class="section-title">4. 월간 캘린더 스케줄</div>', unsafe_allow_html=True)
    st.markdown('<p style="color:#334155;font-size:14px;">★ 월급제  ◆ 시급제</p>', unsafe_allow_html=True)
    first_wd, _ = calendar.monthrange(year, month)
    rows, week  = [], [""] * first_wd
    for d in dates:
        o = ", ".join(name_with_marker(n) for n in best_schedule[d]["오픈"]) or "-"
        c = ", ".join(name_with_marker(n) for n in best_schedule[d]["마감"]) or "-"
        week.append(f"{d.day}일\n오픈: {o}\n마감: {c}")
        if len(week) == 7:
            rows.append(week); week = []
    if week:
        rows.append(week + [""] * (7 - len(week)))
    st.dataframe(pd.DataFrame(rows, columns=WEEKDAYS), use_container_width=True, height=500)

    # ── 5. 상세 스케줄표 ─────────────────────────────────────────────────
    st.markdown('<div class="section-title">5. 상세 스케줄표</div>', unsafe_allow_html=True)
    def highlight_shortage(row):
        styles = [""] * len(row)
        cols = list(row.index)
        if row.get("오픈 부족", 0) > 0:
            styles[cols.index("오픈 부족")] = "background-color:#fee2e2; color:#b91c1c; font-weight:bold"
        if row.get("마감 부족", 0) > 0:
            styles[cols.index("마감 부족")] = "background-color:#fee2e2; color:#b91c1c; font-weight:bold"
        return styles
    st.dataframe(result_df.style.apply(highlight_shortage, axis=1), use_container_width=True)

    # ── 6. 직원별 근무 분석 ──────────────────────────────────────────────
    st.markdown('<div class="section-title">6. 직원별 근무 분석</div>', unsafe_allow_html=True)
    def style_by_type(row):
        if row["유형"] == "월급제":
            bg = "background-color:#dbeafe; color:#1e40af"
        else:
            bg = "background-color:#dcfce7; color:#166534"
        styles = [bg] * len(row)
        cols = list(row.index)
        if row["실제근무일수"] != row["목표근무일수"]:
            styles[cols.index("실제근무일수")] = bg + "; font-weight:bold; text-decoration:underline"
        return styles
    st.dataframe(analysis_df.style.apply(style_by_type, axis=1), use_container_width=True)
    st.markdown('<p style="color:#334155;font-size:14px;">🟦 월급제  🟩 시급제  |  실제근무일수 밑줄 = 목표 불일치</p>', unsafe_allow_html=True)

    # ── 7. 💰 월 급여 계산 ───────────────────────────────────────────────
    st.markdown('<div class="section-title">7. 💰 월 급여 계산</div>', unsafe_allow_html=True)
    st.markdown('<p style="color:#334155;font-size:14px;">시급제: 근무시간 기반 자동 계산 (주휴수당 포함) / 월급제: 등록 월급 기준</p>', unsafe_allow_html=True)

    salary_rows = []
    total_labor_cost = 0

    for emp in employees:
        name = emp["이름"]
        if emp["직원유형"] == "시급제":
            hourly    = emp.get("시급", 0)
            open_cnt  = sum(1 for d in dates if name in best_schedule[d]["오픈"])
            close_cnt = sum(1 for d in dates if name in best_schedule[d]["마감"])
            total_h   = open_cnt * emp.get("오픈시간", 8.0) + close_cnt * emp.get("마감시간", 8.0)
            base_pay  = int(hourly * total_h)
            juhu      = int(hourly * 8) if (total_h / (last_day / 7)) >= 15 else 0
            total_pay = base_pay + juhu
            salary_rows.append({
                "직원": name, "유형": "시급제",
                "시급(원)": f"{hourly:,}", "총 근무시간": f"{total_h:.1f}h",
                "기본급(원)": f"{base_pay:,}", "주휴수당(원)": f"{juhu:,}",
                "예상 월 급여(원)": f"{total_pay:,}",
            })
            total_labor_cost += total_pay
        else:
            ms = emp.get("월급", 0)
            salary_rows.append({
                "직원": name, "유형": "월급제",
                "시급(원)": "-", "총 근무시간": "-",
                "기본급(원)": f"{ms:,}", "주휴수당(원)": "포함",
                "예상 월 급여(원)": f"{ms:,}",
            })
            total_labor_cost += ms

    st.dataframe(pd.DataFrame(salary_rows), use_container_width=True)
    st.metric("💼 이번 달 총 인건비 예상", f"{total_labor_cost:,} 원")


# ─────────────────────────────────────────────
# 8. 🔄 대타 매칭
# ─────────────────────────────────────────────

st.markdown("---")
st.markdown('<div class="section-title">8. 🔄 대타 매칭</div>', unsafe_allow_html=True)
st.markdown('<p style="color:#334155;font-size:14px;">결근 발생 시 조건에 맞는 대타 직원을 자동으로 추천합니다</p>', unsafe_allow_html=True)

def save_sub_req(store, orig, req_date, shift):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO substitute_requests (store_name,original_emp,request_date,shift) VALUES (?,?,?,?)",
            (store, orig, req_date.isoformat(), shift)
        )

def load_sub_reqs(store):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM substitute_requests WHERE store_name=? ORDER BY created_at DESC", (store,)
        ).fetchall()

def match_sub(req_id, emp):
    with get_conn() as conn:
        conn.execute("UPDATE substitute_requests SET status='매칭완료',matched_emp=? WHERE id=?", (emp, req_id))

def delete_sub(req_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM substitute_requests WHERE id=?", (req_id,))

employee_names = [e["이름"] for e in employees]
tab_req, tab_list = st.tabs(["대타 요청 등록", "요청 현황 및 매칭"])

with tab_req:
    col_a, col_b, col_c = st.columns(3)
    with col_a: absent_emp = st.selectbox("결근 직원", employee_names, key="absent_emp")
    with col_b: sub_date = st.date_input("결근 날짜", value=date(year, month, 1), key="sub_date")
    with col_c: sub_shift = st.selectbox("결근 교대", SHIFTS, key="sub_shift")

    if st.button("대타 후보 찾기"):
        cands = []
        for emp in employees:
            if emp["이름"] == absent_emp: continue
            if not is_available(emp, sub_date, sub_shift): continue
            if "best_schedule" in st.session_state:
                if any(emp["이름"] in st.session_state["best_schedule"].get(sub_date, {}).get(s, []) for s in SHIFTS):
                    continue
            note = ""
            if sub_shift == "오픈" and "best_schedule" in st.session_state:
                prev = sub_date - timedelta(days=1)
                if prev in st.session_state["best_schedule"]:
                    if emp["이름"] in st.session_state["best_schedule"][prev].get("마감", []):
                        note = "⚠️ 전날 마감"
            cw = sum(1 for d in dates if "best_schedule" in st.session_state and
                     any(emp["이름"] in st.session_state["best_schedule"].get(d, {}).get(s, []) for s in SHIFTS))
            cands.append({"이름": emp["이름"], "유형": emp["직원유형"],
                          "현재 근무일수": cw, "최대 근무": emp["월최대근무횟수"],
                          "비고": note if note else "✅ 가능"})
        if cands:
            st.markdown(f'<p style="color:#166534; background:#dcfce7; padding:12px 16px; border-radius:8px; font-weight:600;">{len(cands)}명의 대타 후보를 찾았습니다.</p>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(cands).sort_values("현재 근무일수"), use_container_width=True)
            st.markdown('<p style="color:#334155;font-size:14px;">💡 현재 근무일수 적은 순 정렬</p>', unsafe_allow_html=True)
            if st.button("대타 요청 DB 등록"):
                save_sub_req(st.session_state.store_name, absent_emp, sub_date, sub_shift)
                st.markdown('<p style="color:#166534; background:#dcfce7; padding:12px 16px; border-radius:8px; font-weight:600;">대타 요청이 등록되었습니다.</p>', unsafe_allow_html=True)
                st.rerun()
        else:
            st.warning("조건에 맞는 대타 후보가 없습니다.")

with tab_list:
    reqs = load_sub_reqs(st.session_state.store_name)
    if not reqs:
        st.info("등록된 대타 요청이 없습니다.")
    else:
        for req in reqs:
            rid, store, orig, rd, shift, status, matched, created = req
            with st.expander(f"[{status}] {rd}  {shift}  —  {orig} 결근"):
                c1, c2 = st.columns(2)
                c1.write(f"**결근 직원** {orig}")
                c2.write(f"**날짜 / 교대** {rd} / {shift}")
                if matched: st.write(f"**매칭된 대타** {matched}")
                if status == "대기중":
                    cm, cd = st.columns(2)
                    with cm:
                        mn = st.selectbox("대타 직원", [e for e in employee_names if e != orig], key=f"m_{rid}")
                        if st.button("매칭 확정", key=f"c_{rid}"):
                            match_sub(rid, mn); st.markdown(f'<p style="color:#166534; background:#dcfce7; padding:12px 16px; border-radius:8px; font-weight:600;">{mn} 확정!</p>', unsafe_allow_html=True); st.rerun()
                    with cd:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("삭제", key=f"d_{rid}"):
                            delete_sub(rid); st.rerun()