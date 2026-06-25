"""
Sleep Correlation Tracker
Tracks sleep metrics, medications (with timing), lifestyle factors,
and computes correlations. Syncs to Google Sheets.
"""

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from datetime import datetime, date, time
import json
import gspread
from google.oauth2.service_account import Credentials
import warnings
warnings.filterwarnings("ignore")

# ── PAGE CONFIG ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Sleep Tracker", page_icon="🌙", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background-color: #0d1117; color: #e6edf3; }
[data-testid="stSidebar"] { background-color: #161b22; }
.metric-card { background:#161b22; border:1px solid #21262d; border-radius:10px;
               padding:18px 22px; margin-bottom:12px; }
.metric-label { font-size:11px; font-weight:600; letter-spacing:0.08em;
                color:#7d8590; text-transform:uppercase; margin-bottom:4px; }
.metric-value { font-size:28px; font-weight:600; color:#58a6ff; font-family:monospace; }
.metric-sub   { font-size:12px; color:#7d8590; margin-top:2px; }
.section-header { font-size:13px; font-weight:600; letter-spacing:0.1em;
                  text-transform:uppercase; color:#58a6ff;
                  border-bottom:1px solid #21262d; padding-bottom:8px; margin-bottom:16px; }
.info-box { background:#1c2128; border:1px solid #30363d; border-radius:8px;
            padding:12px 16px; font-size:12px; color:#8b949e; margin:8px 0; }
label { color:#e6edf3 !important; font-size:13px !important; }
.stButton > button { background:#238636; color:white; border:none;
                     border-radius:6px; font-weight:600; font-size:13px;
                     padding:8px 20px; width:100%; }
</style>
""", unsafe_allow_html=True)

# ── PLOT STYLE ────────────────────────────────────────────────────────────────
BG    = "#0d1117"
CARD  = "#161b22"
BLUE  = "#58a6ff"
GREEN = "#3fb950"
RED   = "#f85149"
ORANGE= "#f78166"
TEXT  = "#e6edf3"
MUTED = "#7d8590"
BORDER= "#21262d"

def style_ax(ax, title="", xlabel="", ylabel=""):
    ax.set_facecolor(CARD)
    ax.tick_params(colors=MUTED, labelsize=9)
    for sp in ax.spines.values(): sp.set_edgecolor(BORDER)
    ax.xaxis.label.set_color(MUTED)
    ax.yaxis.label.set_color(MUTED)
    ax.grid(True, color=BORDER, linewidth=0.6, linestyle="--", alpha=0.6)
    if title:  ax.set_title(title, color=TEXT, fontsize=10, fontweight="600", pad=8)
    if xlabel: ax.set_xlabel(xlabel, fontsize=9)
    if ylabel: ax.set_ylabel(ylabel, fontsize=9)

# ── GOOGLE SHEETS ─────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]

COLUMNS = [
    "date","bedtime","wake_time","sleep_duration_hr","sleep_score","nap_minutes",
    "med1_name","med1_dose","med1_time","med1_hrs_before_bed",
    "med2_name","med2_dose","med2_time","med2_hrs_before_bed",
    "med3_name","med3_dose","med3_time","med3_hrs_before_bed",
    "exercise","exercise_intensity","exercise_hrs_before_bed",
    "stress_level","worked_past_9pm",
    "sleep_location","slept_with",
    "events","notes"
]

@st.cache_resource
def get_gsheet_client(creds_json):
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def load_data(client, sheet_name):
    try:
        ws = client.open(sheet_name).sheet1
        records = ws.get_all_records()
        if not records: return pd.DataFrame()
        df = pd.DataFrame(records)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df
    except Exception as e:
        st.error(f"Could not load sheet: {e}")
        return pd.DataFrame()

def append_row(client, sheet_name, row):
    try:
        sh = client.open(sheet_name)
        ws = sh.sheet1
        if not ws.get_all_values():
            ws.append_row(list(row.keys()))
        ws.append_row(list(row.values()))
        return True
    except Exception as e:
        st.error(f"Could not save: {e}")
        return False

def ensure_header(client, sheet_name):
    try:
        ws = client.open(sheet_name).sheet1
        if not ws.get_all_values():
            ws.append_row(COLUMNS)
    except gspread.SpreadsheetNotFound:
        sh = client.create(sheet_name)
        sh.share(None, perm_type='anyone', role='writer')
        sh.sheet1.append_row(COLUMNS)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def time_to_float(t_str):
    try:
        h, m = map(int, t_str.split(":"))
        return h + m/60
    except: return np.nan

def hours_before_bed(med_time_str, bedtime_str):
    try:
        diff = time_to_float(bedtime_str) - time_to_float(med_time_str)
        if diff < 0: diff += 24
        return round(diff, 2)
    except: return np.nan

def calc_duration(bed_str, wake_str):
    try:
        dur = time_to_float(wake_str) - time_to_float(bed_str)
        if dur < 0: dur += 24
        return round(dur, 2)
    except: return np.nan

def corr_strength(r):
    a = abs(r)
    if a >= 0.7: return "Strong"
    if a >= 0.4: return "Moderate"
    if a >= 0.2: return "Weak"
    return "Negligible"

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🌙 Sleep Tracker")
    st.markdown("---")
    st.markdown('<div class="section-header">Google Sheets Setup</div>', unsafe_allow_html=True)

    creds_input = st.text_area("Service Account JSON", height=120,
                                placeholder='Paste your Google service account JSON here...')
    sheet_name_input = st.text_input("Sheet Name", value="Sleep Tracker Data")

    gsheet_ready = False
    client = None
    df = pd.DataFrame()

    if creds_input.strip():
        try:
            client = get_gsheet_client(creds_input.strip())
            ensure_header(client, sheet_name_input)
            df = load_data(client, sheet_name_input)
            st.success(f"✓ Connected — {len(df)} records")
            gsheet_ready = True
        except Exception as e:
            st.error(f"Connection failed: {e}")

    st.markdown("---")
    st.markdown('<div class="section-header">Demo Mode</div>', unsafe_allow_html=True)
    use_demo = st.checkbox("Use demo data", value=not gsheet_ready)

    if use_demo:
        np.random.seed(42)
        n = 60
        demo_dates = pd.date_range(end=date.today(), periods=n)
        adderall_time = np.random.choice([12.,13.,14.,15.,16.], n)
        bed_time = np.random.uniform(22., 24.5, n)
        hrs_before = bed_time - adderall_time
        hrs_before = np.where(hrs_before < 0, hrs_before+24, hrs_before)
        sleep_score = 70 + hrs_before*2.5 + np.random.normal(0,5,n)
        sleep_score = np.clip(sleep_score, 40, 100)
        sleep_dur = 6 + hrs_before*0.15 + np.random.normal(0,0.4,n)
        exercise = np.random.choice([0,1], n, p=[0.4,0.6])
        alcohol = np.random.choice([0,1,2,3], n, p=[0.5,0.25,0.15,0.1])
        stress = np.random.randint(1,11,n)
        worked_late = np.random.choice([0,1], n, p=[0.7,0.3])
        sleep_score -= alcohol*4 + stress*0.5 + worked_late*3
        sleep_score += exercise*3
        sleep_score = np.clip(sleep_score, 40, 100)
        df = pd.DataFrame({
            "date": demo_dates,
            "sleep_duration_hr": sleep_dur.round(2),
            "sleep_score": sleep_score.round(1),
            "nap_minutes": np.random.choice([0,0,0,20,30,45], n),
            "med1_name": "Adderall",
            "med1_hrs_before_bed": hrs_before.round(2),
            "exercise": exercise,
            "alcohol_drinks": alcohol,
            "stress_level": stress,
            "worked_past_9pm": worked_late,
            "screen_time_before_bed_min": np.random.randint(0,120,n),
        })

# ── TABS ──────────────────────────────────────────────────────────────────────
tab_log, tab_data, tab_corr, tab_med = st.tabs([
    "📝 Log Night", "📊 Data", "🔗 Correlations", "💊 Med Timing"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — LOG
# ══════════════════════════════════════════════════════════════════════════════
with tab_log:
    st.markdown("## Log Last Night")
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('<div class="section-header">Sleep</div>', unsafe_allow_html=True)
        log_date = st.date_input("Date", value=date.today())
        c1, c2 = st.columns(2)
        with c1: bedtime = st.time_input("Bedtime", value=time(23,0))
        bed_str  = bedtime.strftime("%H:%M")
        wake_str = ""
        sleep_dur = st.number_input("Sleep duration (hrs)", value=7.0,
                                     min_value=0.0, max_value=24.0, step=0.25)
        sleep_score_val = st.number_input("Sleep score (0–100)", 0, 100, 75, step=1)
        nap_min = st.number_input("Nap today (min)", 0, 300, 0, step=5)

    with col_b:
        st.markdown('<div class="section-header">Lifestyle</div>', unsafe_allow_html=True)
        exercised = st.checkbox("Exercised today")
        ex_intensity, ex_hrs_before = "", np.nan
        if exercised:
            ex_intensity = st.selectbox("Intensity", ["Light","Moderate","Intense"], index=1)
            ex_hrs_before = st.number_input("Hrs before bed", 0.0, 24.0, 4.0, 0.5, key="ex")
        stress = st.number_input("Stress level (1–10)", 1, 10, 5, step=1)
        worked_late = st.checkbox("Worked past 9 PM")

        st.markdown("**Where did you sleep?**")
        sleep_location = st.radio("Location", ["Home","Elizabeth's","Hotel"], horizontal=True,
                                   label_visibility="collapsed")

        st.markdown("**Slept with?**")
        slept_with = st.radio("With", ["Alone","Elizabeth"], horizontal=True,
                               label_visibility="collapsed")

        events = st.text_input("One-off events (travel, illness…)")
        notes  = st.text_area("Notes", height=60)

    st.markdown('<div class="section-header">Medications / Supplements</div>', unsafe_allow_html=True)
    st.markdown('<div class="info-box">Check each medication taken. Use + to add a second dose if you took it twice.</div>', unsafe_allow_html=True)

    # Pre-defined medication list (display name, default dose, unit)
    PRESET_MEDS = [
        ("Vitamin A",          "20",   "mg"),
        ("Vitamin K",          "100",  "mg"),
        ("Unisom",             "50",   "mg"),
        ("Vitamin B12",        "1000", "mcg"),
        ("Magnesium",          "400",  "mg"),
        ("Magnesium Glyconate","400",  "mg"),
        ("Magnesium Threonate","2000", "mg"),
        ("Vitamin C",          "500",  "mg"),
        ("L-Arginine",         "3000", "mg"),
        ("L-Carnitine",        "1800", "mg"),
        ("Vitamin T",          "50",   "mg"),
        ("Vitamin G",          "600",  "mg"),
    ]

    med_rows = []
    for med_name, default_dose, unit in PRESET_MEDS:
        took = st.checkbox(med_name, key=f"chk_{med_name}")
        if took:
            # How many doses today?
            num_doses = st.number_input(f"How many doses of {med_name}?",
                                         1, 4, 1, step=1, key=f"ndoses_{med_name}")
            for d in range(int(num_doses)):
                label = f"Dose {d+1}" if num_doses > 1 else "Dose"
                c1, c2 = st.columns(2)
                with c1:
                    dose_val = st.text_input(f"{label} amount",
                                              value=f"{default_dose}{unit}",
                                              key=f"dose_{med_name}_{d}")
                with c2:
                    med_t = st.time_input(f"{label} time taken",
                                           key=f"time_{med_name}_{d}",
                                           value=time(12,0))
                mtime_str = med_t.strftime("%H:%M")
                hrs_bf = hours_before_bed(mtime_str, bed_str)
                st.markdown(f'<div class="info-box">⏱ {med_name} {label} — {dose_val} taken <strong>{hrs_bf:.1f} hrs</strong> before bed</div>', unsafe_allow_html=True)
                med_rows.append({"name": f"{med_name} (dose {d+1})" if num_doses > 1 else med_name,
                                  "dose": dose_val, "time": mtime_str, "hrs": hrs_bf})

    # Custom medications
    st.markdown("**➕ Add custom medication**")
    num_custom = st.number_input("How many custom meds to add?", 0, 5, 0, step=1)
    for i in range(int(num_custom)):
        c1, c2, c3 = st.columns([2,1,1])
        with c1: cname = st.text_input(f"Custom Med {i+1} name", key=f"cname{i}")
        with c2: cdose = st.text_input("Dose", key=f"cdose{i}", placeholder="e.g. 10mg")
        with c3: ctime = st.time_input("Time", key=f"ctime{i}", value=time(12,0))
        if cname.strip():
            ctime_str = ctime.strftime("%H:%M")
            hrs_bf = hours_before_bed(ctime_str, bed_str)
            st.markdown(f'<div class="info-box">⏱ {cname} — {cdose} taken <strong>{hrs_bf:.1f} hrs</strong> before bed</div>', unsafe_allow_html=True)
            med_rows.append({"name": cname, "dose": cdose, "time": ctime_str, "hrs": hrs_bf})

    # Pad to at least 3 slots for sheet compatibility
    while len(med_rows) < 3:
        med_rows.append({"name":"","dose":"","time":"","hrs":np.nan})

    st.markdown("---")
    if st.button("💾 Save Entry"):
        row = {
            "date":str(log_date),"bedtime":bed_str,"wake_time":wake_str,
            "sleep_duration_hr":sleep_dur,"sleep_score":sleep_score_val,"nap_minutes":nap_min,
            "med1_name":med_rows[0]["name"],"med1_dose":med_rows[0]["dose"],
            "med1_time":med_rows[0]["time"],"med1_hrs_before_bed":med_rows[0]["hrs"],
            "med2_name":med_rows[1]["name"],"med2_dose":med_rows[1]["dose"],
            "med2_time":med_rows[1]["time"],"med2_hrs_before_bed":med_rows[1]["hrs"],
            "med3_name":med_rows[2]["name"],"med3_dose":med_rows[2]["dose"],
            "med3_time":med_rows[2]["time"],"med3_hrs_before_bed":med_rows[2]["hrs"],
            # Store all meds as JSON string for full fidelity
            "all_meds": str([{"name":m["name"],"dose":m["dose"],"time":m["time"],"hrs":m["hrs"]} for m in med_rows if m["name"]]),
            "exercise":int(exercised),"exercise_intensity":ex_intensity,
            "exercise_hrs_before_bed":ex_hrs_before,
            "stress_level":stress,"worked_past_9pm":int(worked_late),
            "sleep_location":sleep_location,"slept_with":slept_with,
            "events":events,"notes":notes
        }
        if gsheet_ready and not use_demo:
            if append_row(client, sheet_name_input, row):
                st.success("✓ Saved to Google Sheets")
                st.cache_resource.clear()
        else:
            st.info("Demo mode — connect a sheet to save data.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — DATA
# ══════════════════════════════════════════════════════════════════════════════
with tab_data:
    st.markdown("## Sleep Log")
    if df.empty:
        st.info("No data yet.")
    else:
        show_cols = [c for c in ["date","sleep_duration_hr","sleep_score","nap_minutes",
            "med1_name","med1_hrs_before_bed","exercise",
            "stress_level","worked_past_9pm","sleep_location","slept_with","events"]
            if c in df.columns]
        st.dataframe(df[show_cols].sort_values("date",ascending=False), use_container_width=True)

        m1,m2,m3,m4 = st.columns(4)
        for col, label, val in [
            (m1,"Avg Sleep Score", f"{df['sleep_score'].mean():.1f}" if 'sleep_score' in df else "—"),
            (m2,"Avg Duration",    f"{df['sleep_duration_hr'].mean():.1f}h" if 'sleep_duration_hr' in df else "—"),
            (m3,"Nights Logged",   str(len(df))),
            (m4,"Exercise Days",   f"{df['exercise'].mean()*100:.0f}%" if 'exercise' in df else "—"),
        ]:
            with col:
                st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{val}</div></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — CORRELATIONS
# ══════════════════════════════════════════════════════════════════════════════
with tab_corr:
    st.markdown("## Correlation Analysis")
    if df.empty or len(df) < 5:
        st.info("Need at least 5 nights of data.")
    else:
        target = st.selectbox("Outcome", ["sleep_score","sleep_duration_hr"],
            format_func=lambda x: {"sleep_score":"Sleep Score","sleep_duration_hr":"Sleep Duration"}[x])

        # Create binary columns for location/partner for correlation
        if "sleep_location" in df.columns:
            df["sleep_location_home"]      = (df["sleep_location"] == "Home").astype(int)
            df["sleep_location_elizabeth"] = (df["sleep_location"] == "Elizabeth's").astype(int)
        if "slept_with" in df.columns:
            df["slept_alone"] = (df["slept_with"] == "Alone").astype(int)

        factor_labels = {
            "med1_hrs_before_bed":"Med 1 — hrs before bed",
            "med2_hrs_before_bed":"Med 2 — hrs before bed",
            "med3_hrs_before_bed":"Med 3 — hrs before bed",
            "exercise":"Exercised (0/1)",
            "stress_level":"Stress Level",
            "worked_past_9pm":"Worked Past 9 PM",
            "sleep_location_home":"Slept at Home (0/1)",
            "sleep_location_elizabeth":"Slept at Elizabeth's (0/1)",
            "slept_alone":"Slept Alone (0/1)",
            "nap_minutes":"Nap Duration (min)"
        }

        results = []
        for col, label in factor_labels.items():
            if col not in df.columns or target not in df.columns: continue
            sub = df[[target,col]].dropna().astype(float)
            if len(sub) < 5: continue
            r, p = stats.pearsonr(sub[col], sub[target])
            rho, _ = stats.spearmanr(sub[col], sub[target])
            results.append({"Factor":label,"r":round(r,3),"rho":round(rho,3),
                            "p":round(p,4),"Strength":corr_strength(r),
                            "Sig":"✓" if p<0.05 else ""})

        if results:
            res_df = pd.DataFrame(results).sort_values("r", key=abs, ascending=False)
            st.dataframe(res_df.rename(columns={"r":"Pearson r","rho":"Spearman ρ",
                                                  "p":"p-value","Sig":"Significant"}),
                         use_container_width=True, hide_index=True)

            # Bar chart
            fig, ax = plt.subplots(figsize=(9,4), facecolor=BG)
            sorted_df = res_df.sort_values("r", key=abs)
            colors = [GREEN if r>0 else RED for r in sorted_df["r"]]
            bars = ax.barh(sorted_df["Factor"], sorted_df["r"], color=colors, alpha=0.85, edgecolor=BORDER)
            ax.axvline(0, color=BLUE, linewidth=1.5)
            for bar, val in zip(bars, sorted_df["r"]):
                xpos = val + (0.01 if val >= 0 else -0.01)
                ax.text(xpos, bar.get_y()+bar.get_height()/2, f"{val:+.3f}",
                        va="center", ha="left" if val>=0 else "right",
                        color=TEXT, fontsize=9, fontweight="600")
            style_ax(ax, f"Pearson r vs {target.replace('_',' ').title()}", "Correlation Coefficient")
            ax.set_xlim(-0.8, 0.8)
            fig.tight_layout()
            st.pyplot(fig)
            plt.close(fig)

            # Scatter plots
            st.markdown("### Scatter Plots")
            top = res_df.head(4)
            fig2, axes = plt.subplots(2, 2, figsize=(10,7), facecolor=BG)
            axes = axes.flatten()
            factor_col_map = {v:k for k,v in factor_labels.items()}
            for idx, (_, row) in enumerate(top.iterrows()):
                fcol = factor_col_map.get(row["Factor"])
                if not fcol or fcol not in df.columns: continue
                sub = df[[target,fcol]].dropna().astype(float)
                ax = axes[idx]
                ax.scatter(sub[fcol], sub[target], color=BLUE, s=30, alpha=0.7, edgecolors=BORDER, linewidth=0.3)
                m, b = np.polyfit(sub[fcol], sub[target], 1)
                xl = np.linspace(sub[fcol].min(), sub[fcol].max(), 50)
                ax.plot(xl, m*xl+b, color=ORANGE, linewidth=2, linestyle="--")
                ax.text(0.97, 0.95, f"r={row['r']:+.3f}", transform=ax.transAxes,
                        color=GREEN if row["r"]>0 else RED, fontsize=10,
                        fontweight="700", ha="right", va="top")
                style_ax(ax, row["Factor"], row["Factor"].split("(")[0].strip(), target.replace("_"," "))
            for i in range(len(top),4): axes[i].set_visible(False)
            fig2.tight_layout(pad=1.5)
            st.pyplot(fig2)
            plt.close(fig2)

            st.markdown('<div class="info-box">Pearson r: linear correlation. Spearman ρ: rank-based. p &lt; 0.05 = statistically significant. ✓ = significant.</div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — MED TIMING
# ══════════════════════════════════════════════════════════════════════════════
with tab_med:
    st.markdown("## Medication Timing Analysis")
    st.markdown("*Does taking your medication earlier improve sleep?*")

    if df.empty or len(df) < 5:
        st.info("Need at least 5 nights of data.")
    else:
        med_options = []
        for i in range(1,4):
            nc, hc = f"med{i}_name", f"med{i}_hrs_before_bed"
            if nc in df.columns and hc in df.columns:
                for mname in [m for m in df[nc].dropna().unique() if str(m).strip()]:
                    med_options.append((mname, hc, i))

        if not med_options:
            st.info("No medication data found.")
        else:
            sel = st.selectbox("Select medication", [f"{m[0]} (slot {m[2]})" for m in med_options])
            idx = [f"{m[0]} (slot {m[2]})" for m in med_options].index(sel)
            med_name, hrs_col, slot = med_options[idx]
            nc = f"med{slot}_name"

            sub = df[df[nc]==med_name][[hrs_col,"sleep_score","sleep_duration_hr"]].dropna().astype(float)

            if len(sub) < 5:
                st.warning(f"Only {len(sub)} entries. Need at least 5.")
            else:
                r_score, p_score = stats.pearsonr(sub[hrs_col], sub["sleep_score"])
                r_dur, p_dur     = stats.pearsonr(sub[hrs_col], sub["sleep_duration_hr"])

                st.markdown(f"### {med_name} — {len(sub)} nights")
                c1,c2,c3 = st.columns(3)
                with c1: st.markdown(f'<div class="metric-card"><div class="metric-label">Avg Hrs Before Bed</div><div class="metric-value">{sub[hrs_col].mean():.1f}h</div></div>', unsafe_allow_html=True)
                with c2: st.markdown(f'<div class="metric-card"><div class="metric-label">r vs Sleep Score</div><div class="metric-value" style="color:{GREEN if r_score>0 else RED}">{r_score:+.3f}</div><div class="metric-sub">{corr_strength(r_score)} {"✓ sig" if p_score<0.05 else ""}</div></div>', unsafe_allow_html=True)
                with c3: st.markdown(f'<div class="metric-card"><div class="metric-label">r vs Duration</div><div class="metric-value" style="color:{GREEN if r_dur>0 else RED}">{r_dur:+.3f}</div><div class="metric-sub">{corr_strength(r_dur)} {"✓ sig" if p_dur<0.05 else ""}</div></div>', unsafe_allow_html=True)

                # Scatter plot
                fig, axes = plt.subplots(1, 2, figsize=(11,4), facecolor=BG)

                ax = axes[0]
                ax.scatter(sub[hrs_col], sub["sleep_score"],
                           c=sub["sleep_score"], cmap="YlGn", vmin=40, vmax=100,
                           s=50, alpha=0.8, edgecolors=BORDER, linewidth=0.4)
                m, b = np.polyfit(sub[hrs_col], sub["sleep_score"], 1)
                xl = np.linspace(sub[hrs_col].min(), sub[hrs_col].max(), 100)
                ax.plot(xl, m*xl+b, color=ORANGE, linewidth=2.2, linestyle="--")
                ax.text(0.05, 0.93, f"r = {r_score:+.3f}{'*' if p_score<0.05 else ''}",
                        transform=ax.transAxes, color=GREEN if r_score>0 else RED,
                        fontsize=11, fontweight="700")
                style_ax(ax, f"{med_name}: Hrs Before Bed vs Score",
                         "Hours Between Dose & Bedtime", "Sleep Score")

                # Early vs late bar
                threshold = st.number_input("Early = taken more than X hrs before bed", 1.0, 20.0, 8.0, step=0.5)
                sub2 = sub.copy()
                sub2["timing"] = np.where(sub2[hrs_col]>=threshold, "Early", "Late")
                grouped = sub2.groupby("timing")["sleep_score"].mean()

                ax2 = axes[1]
                bar_colors = [GREEN if t=="Early" else RED for t in grouped.index]
                bars = ax2.bar(grouped.index, grouped.values, color=bar_colors, alpha=0.85,
                               edgecolor=BORDER, width=0.5)
                for bar, val in zip(bars, grouped.values):
                    ax2.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.5,
                             f"{val:.1f}", ha="center", va="bottom",
                             color=TEXT, fontsize=12, fontweight="700")
                style_ax(ax2, f"Early (≥{threshold:.0f}h) vs Late (<{threshold:.0f}h)",
                         "Timing", "Avg Sleep Score")
                ax2.set_ylim(0, max(grouped.values)*1.15)

                fig.tight_layout(pad=1.5)
                st.pyplot(fig)
                plt.close(fig)

                st.markdown(f'<div class="info-box">Positive r = taking {med_name} earlier correlates with better sleep. Early = ≥{threshold:.0f}h before bed.</div>', unsafe_allow_html=True)
