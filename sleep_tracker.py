"""
Sleep Correlation Tracker
Tracks sleep metrics, medications (with timing), lifestyle factors,
and computes correlations. Syncs to Google Sheets.
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import stats
from datetime import datetime, date, time
import json
import gspread
from google.oauth2.service_account import Credentials
import warnings
warnings.filterwarnings("ignore")

# ── PAGE CONFIG ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Sleep Tracker",
    page_icon="🌙",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── STYLE ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

  html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

  /* Dark navy background */
  .stApp { background-color: #0d1117; color: #e6edf3; }

  /* Sidebar */
  [data-testid="stSidebar"] { background-color: #161b22; border-right: 1px solid #21262d; }

  /* Cards */
  .metric-card {
    background: #161b22;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 18px 22px;
    margin-bottom: 12px;
  }
  .metric-label { font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
                  color: #7d8590; text-transform: uppercase; margin-bottom: 4px; }
  .metric-value { font-size: 28px; font-weight: 600; color: #58a6ff;
                  font-family: 'JetBrains Mono', monospace; }
  .metric-sub   { font-size: 12px; color: #7d8590; margin-top: 2px; }

  /* Section headers */
  .section-header {
    font-size: 13px; font-weight: 600; letter-spacing: 0.1em;
    text-transform: uppercase; color: #58a6ff;
    border-bottom: 1px solid #21262d; padding-bottom: 8px; margin-bottom: 16px;
  }

  /* Correlation badge */
  .corr-positive { color: #3fb950; font-weight: 600; }
  .corr-negative { color: #f85149; font-weight: 600; }
  .corr-neutral  { color: #7d8590; font-weight: 600; }

  /* Input labels */
  label { color: #e6edf3 !important; font-size: 13px !important; }

  /* Buttons */
  .stButton > button {
    background: #238636; color: white; border: none;
    border-radius: 6px; font-weight: 600; font-size: 13px;
    padding: 8px 20px; width: 100%;
  }
  .stButton > button:hover { background: #2ea043; }

  div[data-testid="stNumberInput"] input,
  div[data-testid="stTextInput"] input,
  div[data-testid="stTimeInput"] input,
  div[data-testid="stSelectbox"] select,
  div[data-testid="stMultiSelect"] { background: #0d1117 !important; color: #e6edf3 !important; }

  .info-box {
    background: #1c2128; border: 1px solid #30363d;
    border-radius: 8px; padding: 12px 16px;
    font-size: 12px; color: #8b949e; margin: 8px 0;
  }
</style>
""", unsafe_allow_html=True)


# ── GOOGLE SHEETS CONNECTION ──────────────────────────────────────────────────
SHEET_NAME = "Sleep Tracker Data"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

@st.cache_resource
def get_gsheet_client(creds_json: str):
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def load_data_from_sheet(client, sheet_name: str) -> pd.DataFrame:
    try:
        sh = client.open(sheet_name)
        ws = sh.sheet1
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception as e:
        st.error(f"Could not load sheet: {e}")
        return pd.DataFrame()

def append_row_to_sheet(client, sheet_name: str, row: dict):
    try:
        sh = client.open(sheet_name)
        ws = sh.sheet1
        # Create header if sheet is empty
        if ws.row_count == 0 or not ws.get_all_values():
            ws.append_row(list(row.keys()))
        ws.append_row(list(row.values()))
        return True
    except Exception as e:
        st.error(f"Could not write to sheet: {e}")
        return False

def ensure_sheet_header(client, sheet_name: str, columns: list):
    """Create sheet with headers if it doesn't exist."""
    try:
        sh = client.open(sheet_name)
        ws = sh.sheet1
        existing = ws.get_all_values()
        if not existing:
            ws.append_row(columns)
    except gspread.SpreadsheetNotFound:
        sh = client.create(sheet_name)
        sh.share(None, perm_type='anyone', role='writer')
        ws = sh.sheet1
        ws.append_row(columns)


# ── HELPERS ───────────────────────────────────────────────────────────────────
COLUMNS = [
    "date", "bedtime", "wake_time", "sleep_duration_hr", "sleep_score",
    "nap_minutes",
    # Medications (up to 3 slots)
    "med1_name", "med1_dose", "med1_time", "med1_hrs_before_bed",
    "med2_name", "med2_dose", "med2_time", "med2_hrs_before_bed",
    "med3_name", "med3_dose", "med3_time", "med3_hrs_before_bed",
    # Lifestyle
    "exercise", "exercise_intensity", "exercise_hrs_before_bed",
    "alcohol_drinks", "alcohol_hrs_before_bed",
    "stress_level",
    "screen_time_before_bed_min",
    # Events / notes
    "events", "notes"
]

def time_to_float(t_str: str) -> float:
    """Convert HH:MM string to decimal hours."""
    try:
        h, m = map(int, t_str.split(":"))
        return h + m / 60
    except:
        return np.nan

def hours_before_bed(med_time_str: str, bedtime_str: str) -> float:
    """Calculate how many hours before bed a medication was taken."""
    try:
        med_h = time_to_float(med_time_str)
        bed_h = time_to_float(bedtime_str)
        # Handle crossing midnight
        diff = bed_h - med_h
        if diff < 0:
            diff += 24
        return round(diff, 2)
    except:
        return np.nan

def calc_duration(bedtime_str: str, wake_str: str) -> float:
    try:
        bed = time_to_float(bedtime_str)
        wake = time_to_float(wake_str)
        dur = wake - bed
        if dur < 0:
            dur += 24
        return round(dur, 2)
    except:
        return np.nan

def corr_strength(r: float) -> str:
    a = abs(r)
    if a >= 0.7: return "Strong"
    if a >= 0.4: return "Moderate"
    if a >= 0.2: return "Weak"
    return "Negligible"

def corr_color_class(r: float) -> str:
    if r > 0.15: return "corr-positive"
    if r < -0.15: return "corr-negative"
    return "corr-neutral"


# ── SIDEBAR: CREDENTIALS ──────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🌙 Sleep Tracker")
    st.markdown("---")

    st.markdown('<div class="section-header">Google Sheets Setup</div>', unsafe_allow_html=True)
    creds_input = st.text_area(
        "Service Account JSON",
        height=120,
        placeholder='Paste your Google service account JSON here...',
        help="Download from Google Cloud Console → IAM → Service Accounts → Keys"
    )
    sheet_name_input = st.text_input("Sheet Name", value=SHEET_NAME)

    gsheet_ready = False
    client = None
    df = pd.DataFrame()

    if creds_input.strip():
        try:
            client = get_gsheet_client(creds_input.strip())
            ensure_sheet_header(client, sheet_name_input, COLUMNS)
            df = load_data_from_sheet(client, sheet_name_input)
            st.success(f"✓ Connected — {len(df)} records")
            gsheet_ready = True
        except Exception as e:
            st.error(f"Connection failed: {e}")

    st.markdown("---")
    st.markdown('<div class="section-header">Demo Mode</div>', unsafe_allow_html=True)
    use_demo = st.checkbox("Use demo data (no sheet needed)", value=not gsheet_ready)

    if use_demo:
        np.random.seed(42)
        n = 60
        demo_dates = pd.date_range(end=date.today(), periods=n)
        adderall_time = np.random.choice([12.0, 13.0, 14.0, 15.0, 16.0], n)
        bed_time = np.random.uniform(22.0, 24.5, n)
        hrs_before = bed_time - adderall_time
        hrs_before = np.where(hrs_before < 0, hrs_before + 24, hrs_before)
        sleep_score = 70 + hrs_before * 2.5 + np.random.normal(0, 5, n)
        sleep_score = np.clip(sleep_score, 40, 100)
        sleep_dur = 6 + hrs_before * 0.15 + np.random.normal(0, 0.4, n)
        exercise = np.random.choice([0, 1], n, p=[0.4, 0.6])
        alcohol = np.random.choice([0, 1, 2, 3], n, p=[0.5, 0.25, 0.15, 0.1])
        stress = np.random.randint(1, 11, n)
        sleep_score -= alcohol * 4 + stress * 0.5
        sleep_score += exercise * 3
        sleep_score = np.clip(sleep_score, 40, 100)

        df = pd.DataFrame({
            "date": demo_dates,
            "sleep_duration_hr": sleep_dur.round(2),
            "sleep_score": sleep_score.round(1),
            "nap_minutes": np.random.choice([0, 0, 0, 20, 30, 45], n),
            "med1_name": "Adderall",
            "med1_dose": "20mg",
            "med1_hrs_before_bed": hrs_before.round(2),
            "exercise": exercise,
            "exercise_intensity": np.where(exercise, np.random.choice(["Light","Moderate","Intense"], n), ""),
            "alcohol_drinks": alcohol,
            "stress_level": stress,
            "screen_time_before_bed_min": np.random.randint(0, 120, n),
            "events": "",
            "notes": ""
        })


# ── TABS ──────────────────────────────────────────────────────────────────────
tab_log, tab_data, tab_corr, tab_med = st.tabs([
    "📝 Log Night", "📊 Data", "🔗 Correlations", "💊 Med Timing"
])


# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — LOG NIGHT
# ══════════════════════════════════════════════════════════════════════════════
with tab_log:
    st.markdown("## Log Last Night")

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('<div class="section-header">Sleep</div>', unsafe_allow_html=True)
        log_date = st.date_input("Date (morning of)", value=date.today())
        c1, c2 = st.columns(2)
        with c1:
            bedtime = st.time_input("Bedtime", value=time(23, 0))
        with c2:
            wake_time = st.time_input("Wake time", value=time(7, 0))

        bed_str  = bedtime.strftime("%H:%M")
        wake_str = wake_time.strftime("%H:%M")
        auto_dur = calc_duration(bed_str, wake_str)
        sleep_dur = st.number_input("Sleep duration (hrs)", value=auto_dur,
                                    min_value=0.0, max_value=24.0, step=0.25)
        sleep_score_val = st.slider("Sleep score (Fitbit/Oura)", 0, 100, 75)
        nap_min = st.number_input("Nap today (minutes)", 0, 300, 0, step=5)

    with col_b:
        st.markdown('<div class="section-header">Lifestyle</div>', unsafe_allow_html=True)
        exercised = st.checkbox("Exercised today")
        ex_intensity = ""
        ex_hrs_before = np.nan
        if exercised:
            ex_intensity = st.select_slider("Intensity",
                options=["Light", "Moderate", "Intense"], value="Moderate")
            ex_hrs_before = st.number_input("Hours before bed", 0.0, 24.0, 4.0, 0.5,
                                             key="ex_hrs")

        alcohol = st.number_input("Alcoholic drinks", 0, 20, 0)
        alc_hrs = np.nan
        if alcohol > 0:
            alc_hrs = st.number_input("Last drink (hrs before bed)", 0.0, 24.0, 3.0, 0.5)

        stress = st.slider("Stress level (1–10)", 1, 10, 5)
        screen_min = st.number_input("Screen time before bed (min)", 0, 300, 30, 5)

        events = st.text_input("One-off events (travel, illness, conflict…)")
        notes  = st.text_area("Notes", height=60)

    # ── MEDICATIONS ────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Medications / Supplements</div>',
                unsafe_allow_html=True)
    st.markdown('<div class="info-box">For each medication, enter the time you took it. The app calculates hours before bedtime automatically.</div>',
                unsafe_allow_html=True)

    med_rows = []
    for i in range(1, 4):
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            mname = st.text_input(f"Med {i} name", key=f"mname{i}",
                                   placeholder="e.g. Adderall, Melatonin")
        with c2:
            mdose = st.text_input(f"Dose", key=f"mdose{i}", placeholder="e.g. 20mg")
        with c3:
            mtime = st.time_input(f"Time taken", key=f"mtime{i}",
                                   value=time(12, 0))

        if mname.strip():
            mtime_str = mtime.strftime("%H:%M")
            hrs_bf = hours_before_bed(mtime_str, bed_str)
            st.markdown(
                f'<div class="info-box">⏱ {mname} taken <strong>{hrs_bf:.1f} hrs</strong> before bed</div>',
                unsafe_allow_html=True)
            med_rows.append({
                "name": mname, "dose": mdose,
                "time": mtime_str, "hrs_before_bed": hrs_bf
            })
        else:
            med_rows.append({"name":"","dose":"","time":"","hrs_before_bed":np.nan})

    # ── SAVE ───────────────────────────────────────────────────────────────
    st.markdown("---")
    if st.button("💾 Save Entry"):
        row = {
            "date": str(log_date),
            "bedtime": bed_str, "wake_time": wake_str,
            "sleep_duration_hr": sleep_dur, "sleep_score": sleep_score_val,
            "nap_minutes": nap_min,
            "med1_name": med_rows[0]["name"], "med1_dose": med_rows[0]["dose"],
            "med1_time": med_rows[0]["time"], "med1_hrs_before_bed": med_rows[0]["hrs_before_bed"],
            "med2_name": med_rows[1]["name"], "med2_dose": med_rows[1]["dose"],
            "med2_time": med_rows[1]["time"], "med2_hrs_before_bed": med_rows[1]["hrs_before_bed"],
            "med3_name": med_rows[2]["name"], "med3_dose": med_rows[2]["dose"],
            "med3_time": med_rows[2]["time"], "med3_hrs_before_bed": med_rows[2]["hrs_before_bed"],
            "exercise": int(exercised), "exercise_intensity": ex_intensity,
            "exercise_hrs_before_bed": ex_hrs_before,
            "alcohol_drinks": alcohol, "alcohol_hrs_before_bed": alc_hrs,
            "stress_level": stress,
            "screen_time_before_bed_min": screen_min,
            "events": events, "notes": notes
        }
        if gsheet_ready and not use_demo:
            ok = append_row_to_sheet(client, sheet_name_input, row)
            if ok:
                st.success("✓ Saved to Google Sheets")
                st.cache_resource.clear()
        elif use_demo:
            st.info("Demo mode — entry not saved. Connect a sheet to persist data.")
        else:
            st.warning("No sheet connected. Entry not saved.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — DATA TABLE
# ══════════════════════════════════════════════════════════════════════════════
with tab_data:
    st.markdown("## Sleep Log")
    if df.empty:
        st.info("No data yet. Log your first night or enable demo mode.")
    else:
        display_cols = [c for c in [
            "date","sleep_duration_hr","sleep_score","nap_minutes",
            "med1_name","med1_hrs_before_bed",
            "med2_name","med2_hrs_before_bed",
            "exercise","alcohol_drinks","stress_level",
            "screen_time_before_bed_min","events"
        ] if c in df.columns]
        st.dataframe(df[display_cols].sort_values("date", ascending=False),
                     use_container_width=True)

        # Quick summary metrics
        st.markdown("### Summary")
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            avg_score = df["sleep_score"].mean() if "sleep_score" in df else 0
            st.markdown(f'<div class="metric-card"><div class="metric-label">Avg Sleep Score</div><div class="metric-value">{avg_score:.1f}</div></div>', unsafe_allow_html=True)
        with m2:
            avg_dur = df["sleep_duration_hr"].mean() if "sleep_duration_hr" in df else 0
            st.markdown(f'<div class="metric-card"><div class="metric-label">Avg Duration</div><div class="metric-value">{avg_dur:.1f}h</div></div>', unsafe_allow_html=True)
        with m3:
            n_rec = len(df)
            st.markdown(f'<div class="metric-card"><div class="metric-label">Nights Logged</div><div class="metric-value">{n_rec}</div></div>', unsafe_allow_html=True)
        with m4:
            ex_pct = df["exercise"].mean() * 100 if "exercise" in df else 0
            st.markdown(f'<div class="metric-card"><div class="metric-label">Exercise Days</div><div class="metric-value">{ex_pct:.0f}%</div></div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — CORRELATIONS
# ══════════════════════════════════════════════════════════════════════════════
with tab_corr:
    st.markdown("## Correlation Analysis")

    if df.empty or len(df) < 5:
        st.info("Need at least 5 nights of data for correlations.")
    else:
        target = st.selectbox("Outcome to analyze",
            ["sleep_score", "sleep_duration_hr"], format_func=lambda x: {
                "sleep_score": "Sleep Score",
                "sleep_duration_hr": "Sleep Duration (hrs)"
            }[x])

        factors = []
        for col in ["med1_hrs_before_bed","med2_hrs_before_bed","med3_hrs_before_bed",
                    "exercise","alcohol_drinks","stress_level",
                    "screen_time_before_bed_min","nap_minutes"]:
            if col in df.columns:
                factors.append(col)

        factor_labels = {
            "med1_hrs_before_bed": "Med 1 — hrs before bed",
            "med2_hrs_before_bed": "Med 2 — hrs before bed",
            "med3_hrs_before_bed": "Med 3 — hrs before bed",
            "exercise": "Exercised (0/1)",
            "alcohol_drinks": "Alcohol (drinks)",
            "stress_level": "Stress Level",
            "screen_time_before_bed_min": "Screen Time (min)",
            "nap_minutes": "Nap Duration (min)"
        }

        if target not in df.columns:
            st.warning(f"Column '{target}' not in data.")
        else:
            results = []
            for f in factors:
                if f not in df.columns:
                    continue
                sub = df[[target, f]].dropna().astype(float)
                if len(sub) < 5:
                    continue
                r, p = stats.pearsonr(sub[f], sub[target])
                rho, p2 = stats.spearmanr(sub[f], sub[target])
                results.append({
                    "Factor": factor_labels.get(f, f),
                    "Pearson r": round(r, 3),
                    "Spearman ρ": round(rho, 3),
                    "p-value": round(p, 4),
                    "Strength": corr_strength(r),
                    "Direction": "↑ Positive" if r > 0 else "↓ Negative",
                    "Significant": "✓" if p < 0.05 else ""
                })

            if results:
                res_df = pd.DataFrame(results).sort_values("Pearson r", key=abs, ascending=False)

                # Correlation bar chart
                fig = go.Figure()
                colors = ["#3fb950" if r > 0 else "#f85149" for r in res_df["Pearson r"]]
                fig.add_trace(go.Bar(
                    x=res_df["Pearson r"],
                    y=res_df["Factor"],
                    orientation="h",
                    marker_color=colors,
                    text=[f"{r:+.3f}" for r in res_df["Pearson r"]],
                    textposition="outside"
                ))
                fig.update_layout(
                    title=f"Pearson r vs {target.replace('_',' ').title()}",
                    paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                    font=dict(color="#e6edf3", size=12),
                    xaxis=dict(range=[-1, 1], gridcolor="#21262d", zeroline=True,
                               zerolinecolor="#58a6ff", zerolinewidth=1.5),
                    yaxis=dict(gridcolor="#21262d"),
                    height=350, margin=dict(l=10, r=60, t=40, b=10)
                )
                st.plotly_chart(fig, use_container_width=True)

                st.dataframe(res_df, use_container_width=True, hide_index=True)

                st.markdown('<div class="info-box">Pearson r measures linear correlation (−1 to +1). Spearman ρ is rank-based and more robust to outliers. p < 0.05 = statistically significant given your sample size.</div>', unsafe_allow_html=True)

                # Scatter plots
                st.markdown("### Scatter Plots")
                top_factors = res_df["Factor"].head(4).tolist()
                factor_col_map = {v: k for k, v in factor_labels.items()}

                ncols = 2
                nrows = (len(top_factors) + 1) // 2
                fig2 = make_subplots(rows=nrows, cols=ncols,
                    subplot_titles=top_factors)

                for idx, fname in enumerate(top_factors):
                    fcol = factor_col_map.get(fname, fname)
                    if fcol not in df.columns:
                        continue
                    sub = df[[target, fcol]].dropna().astype(float)
                    r = idx // ncols + 1
                    c = idx % ncols + 1
                    fig2.add_trace(go.Scatter(
                        x=sub[fcol], y=sub[target],
                        mode="markers",
                        marker=dict(color="#58a6ff", size=7, opacity=0.7),
                        name=fname
                    ), row=r, col=c)
                    # Trend line
                    if len(sub) > 2:
                        m, b = np.polyfit(sub[fcol], sub[target], 1)
                        x_line = np.linspace(sub[fcol].min(), sub[fcol].max(), 50)
                        fig2.add_trace(go.Scatter(
                            x=x_line, y=m * x_line + b,
                            mode="lines", line=dict(color="#f78166", width=2),
                            showlegend=False
                        ), row=r, col=c)

                fig2.update_layout(
                    paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                    font=dict(color="#e6edf3", size=11),
                    showlegend=False, height=400,
                    margin=dict(l=10, r=10, t=40, b=10)
                )
                fig2.update_xaxes(gridcolor="#21262d")
                fig2.update_yaxes(gridcolor="#21262d")
                st.plotly_chart(fig2, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — MED TIMING DEEP DIVE
# ══════════════════════════════════════════════════════════════════════════════
with tab_med:
    st.markdown("## Medication Timing Analysis")
    st.markdown("*Does taking your medication earlier improve sleep?*")

    if df.empty or len(df) < 5:
        st.info("Need at least 5 nights of data.")
    else:
        # Pick which med slot to analyze
        med_options = []
        for i in range(1, 4):
            name_col = f"med{i}_name"
            hrs_col  = f"med{i}_hrs_before_bed"
            if name_col in df.columns and hrs_col in df.columns:
                med_names = df[name_col].dropna().unique()
                med_names = [m for m in med_names if str(m).strip()]
                for mname in med_names:
                    med_options.append((mname, hrs_col, i))

        if not med_options:
            st.info("No medication data found.")
        else:
            selected_med = st.selectbox(
                "Select medication to analyze",
                options=[f"{m[0]} (slot {m[2]})" for m in med_options]
            )
            sel_idx = [f"{m[0]} (slot {m[2]})" for m in med_options].index(selected_med)
            med_name, hrs_col, slot = med_options[sel_idx]
            name_col = f"med{slot}_name"

            sub = df[df[name_col] == med_name][[hrs_col, "sleep_score", "sleep_duration_hr"]].dropna()
            sub = sub.astype(float)

            if len(sub) < 5:
                st.warning(f"Only {len(sub)} entries for {med_name}. Need at least 5.")
            else:
                r_score, p_score = stats.pearsonr(sub[hrs_col], sub["sleep_score"])
                r_dur,   p_dur   = stats.pearsonr(sub[hrs_col], sub["sleep_duration_hr"])

                st.markdown(f"### {med_name} — {len(sub)} nights")

                c1, c2, c3 = st.columns(3)
                with c1:
                    avg_hrs = sub[hrs_col].mean()
                    st.markdown(f'<div class="metric-card"><div class="metric-label">Avg Hrs Before Bed</div><div class="metric-value">{avg_hrs:.1f}h</div></div>', unsafe_allow_html=True)
                with c2:
                    sign = "+" if r_score > 0 else ""
                    cls = corr_color_class(r_score)
                    st.markdown(f'<div class="metric-card"><div class="metric-label">r vs Sleep Score</div><div class="metric-value"><span class="{cls}">{sign}{r_score:.3f}</span></div><div class="metric-sub">{corr_strength(r_score)} • {"✓ sig" if p_score < 0.05 else "not sig"}</div></div>', unsafe_allow_html=True)
                with c3:
                    sign = "+" if r_dur > 0 else ""
                    cls = corr_color_class(r_dur)
                    st.markdown(f'<div class="metric-card"><div class="metric-label">r vs Duration</div><div class="metric-value"><span class="{cls}">{sign}{r_dur:.3f}</span></div><div class="metric-sub">{corr_strength(r_dur)} • {"✓ sig" if p_dur < 0.05 else "not sig"}</div></div>', unsafe_allow_html=True)

                # Scatter: hrs before bed vs sleep score
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=sub[hrs_col], y=sub["sleep_score"],
                    mode="markers",
                    marker=dict(color="#58a6ff", size=9, opacity=0.8,
                                line=dict(color="#1f6feb", width=1)),
                    name="Nights",
                    hovertemplate="<b>%{x:.1f}h before bed</b><br>Score: %{y:.0f}<extra></extra>"
                ))
                # Trend
                m, b = np.polyfit(sub[hrs_col], sub["sleep_score"], 1)
                x_line = np.linspace(sub[hrs_col].min(), sub[hrs_col].max(), 100)
                fig.add_trace(go.Scatter(
                    x=x_line, y=m * x_line + b,
                    mode="lines",
                    line=dict(color="#f78166", width=2.5, dash="dot"),
                    name="Trend"
                ))
                fig.update_layout(
                    title=f"{med_name}: Hours Before Bed vs Sleep Score",
                    xaxis_title="Hours Between Dose and Bedtime",
                    yaxis_title="Sleep Score",
                    paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                    font=dict(color="#e6edf3"),
                    xaxis=dict(gridcolor="#21262d"),
                    yaxis=dict(gridcolor="#21262d"),
                    height=380, margin=dict(l=10, r=10, t=40, b=10)
                )
                st.plotly_chart(fig, use_container_width=True)

                # Bucketed bar chart: early vs late dose
                threshold = st.slider(
                    f"Split: 'Early' dose = taken more than X hrs before bed",
                    min_value=4.0, max_value=12.0, value=8.0, step=0.5
                )
                sub["timing"] = np.where(sub[hrs_col] >= threshold, "Early", "Late")
                grouped = sub.groupby("timing")[["sleep_score","sleep_duration_hr"]].mean().reset_index()

                fig2 = make_subplots(rows=1, cols=2,
                    subplot_titles=["Avg Sleep Score", "Avg Duration (hrs)"])
                for col_idx, metric in enumerate(["sleep_score","sleep_duration_hr"]):
                    colors = ["#3fb950" if t == "Early" else "#f85149"
                              for t in grouped["timing"]]
                    fig2.add_trace(go.Bar(
                        x=grouped["timing"], y=grouped[metric],
                        marker_color=colors,
                        text=grouped[metric].round(1),
                        textposition="outside"
                    ), row=1, col=col_idx+1)

                fig2.update_layout(
                    paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
                    font=dict(color="#e6edf3"), showlegend=False,
                    height=320, margin=dict(l=10, r=10, t=40, b=10)
                )
                fig2.update_xaxes(gridcolor="#21262d")
                fig2.update_yaxes(gridcolor="#21262d")
                st.plotly_chart(fig2, use_container_width=True)

                st.markdown(f'<div class="info-box">Early = dose taken ≥{threshold:.0f}h before bed &nbsp;|&nbsp; Late = dose taken &lt;{threshold:.0f}h before bed.<br>Positive r means taking the medication <em>earlier</em> correlates with better sleep.</div>', unsafe_allow_html=True)
