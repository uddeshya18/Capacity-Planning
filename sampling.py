import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- UI THEME ---
st.markdown("""
    <style>
    .stApp, [data-testid="stSidebar"] { background-color: #f8fafc !important; }
    div[data-testid="metric-container"] {
        background-color: #ffffff; border: 1px solid #e2e8f0;
        padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📊 Strategic Capacity Planner")

# --- SIDEBAR ---
st.sidebar.header("⚙️ Global Settings")
if st.sidebar.button("♻️ Reset All Data"):
    st.rerun()

merc_file = st.sidebar.file_uploader("Upload Mercury Metrics (AHT)", type="csv")
qc_file = st.sidebar.file_uploader("Upload Quality Central (Volume)", type="csv")
qas_per_site = st.sidebar.number_input("Current Team 2 Headcount", min_value=0.1, value=10.0)
prod_hours = st.sidebar.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

def get_monday(d):
    return d - timedelta(days=d.weekday())

current_monday = get_monday(datetime.now())

if merc_file and qc_file:
    # 1. LOAD & NORMALIZE
    df_m = pd.read_csv(merc_file)
    df_q = pd.read_csv(qc_file)

    for d in [df_m, df_q]:
        for col in d.columns:
            if d[col].dtype == 'object':
                d[col] = d[col].astype(str).str.strip()

    # AHT Calculation
    df_m['Calc_AHT'] = 3600 * (pd.to_numeric(df_m['Processed Hours'], errors='coerce').fillna(0) + 
                               pd.to_numeric(df_m['Manual Skip Hours'], errors='coerce').fillna(0)) / \
                               pd.to_numeric(df_m['Processed Units'], errors='coerce').replace(0, np.nan)

    # 2. STRICT GHOST TASK PURGE
    # Identify which workflows/locales were actually seen in the last 2 weeks
    all_weeks = sorted(df_q['Audit Creation Period Week'].unique(), reverse=True)
    recent_2_weeks = all_weeks[:2]
    
    active_wf = df_q[df_q['Audit Creation Period Week'].isin(recent_2_weeks)]['workflow_name'].unique()
    active_loc = df_q[df_q['Audit Creation Period Week'].isin(recent_2_weeks)]['locale'].unique()

    # 3. DEDUPLICATION (Batch Level)
    batch_cols = ['execution_batch_id', 'workflow_name', 'locale', 'Audit Creation Period Week']
    df_q_dedup = df_q.groupby(batch_cols).agg({
        'audit_created_units': 'first',
        'production_created_units': 'first'
    }).reset_index()

    # 4. SITE FILTERING & GROWTH (Full History for Trend)
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_sites = st.sidebar.multiselect("Filter Site:", all_sites, default=all_sites)
    site_locales = df_m[df_m['Column-1:Site'].isin(selected_sites)]['Column-2:Locale'].unique()
    
    f_q = df_q_dedup[df_q_dedup['locale'].isin(site_locales)]
    f_m = df_m[df_m['Column-1:Site'].isin(selected_sites)]

    site_growth_val = 0.0
    if not f_q.empty:
        weekly_sum = f_q.groupby('Audit Creation Period Week')['audit_created_units'].sum().sort_index()
        u = weekly_sum.values
        if len(u) > 1:
            diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
            site_growth_val = np.mean(diffs) if diffs else 0.0

    st.sidebar.metric(label="📈 Overall Growth Rate", value=f"{site_growth_val * 100:.2f}%")

    # 5. FINAL CALCULATION DATASET (Only active tasks)
    num_weeks = 4
    recent_4_weeks = all_weeks[:4]
    
    # Filter out January "Ghost" tasks from the baseline entirely
    wf_base = f_q[(f_q['Audit Creation Period Week'].isin(recent_4_weeks)) & (f_q['workflow_name'].isin(active_wf))]
    loc_base = f_q[(f_q['Audit Creation Period Week'].isin(recent_4_weeks)) & (f_q['locale'].isin(active_loc))]

    wf_agg = wf_base.groupby('workflow_name').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
    loc_agg = loc_base.groupby('locale').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()

    def get_trimmed_aht(series):
        clean = series.dropna()
        return clean[clean <= clean.quantile(0.95)].mean() if not clean.empty else 0

    # Color Styling Function
    def color_gap(val):
        color = 'red' if float(val) < 0 else 'green'
        return f'color: {color}; font-weight: bold'

    # --- TABS ---
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 Future Forecast Explorer"])

    with tab1:
        st.subheader("Historical Weekly Average (Active Tasks Only)")
        c1, c2 = st.columns(2)
        with c1:
            wf_h = []
            for _, row in wf_agg.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
                if aht > 0:
                    s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
                    wf_h.append({"Workflow Name": row['workflow_name'], "Avg Weekly Tasks": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "Cleaned AHT (s)": f"{aht:.1f}"})
            st.dataframe(pd.DataFrame(wf_h), use_container_width=True, hide_index=True)
        with c2:
            loc_h = []
            for _, row in loc_agg.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
                if aht > 0:
                    s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
                    loc_h.append({"Locale": row['locale'], "Avg Weekly Tasks": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "Cleaned AHT (s)": f"{aht:.1f}"})
            st.dataframe(pd.DataFrame(loc_h), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Team 2 Task Forecast")
        st.caption(f"📅 **Current Date:** {datetime.now().strftime('%d %b %Y')}")
        week_options = [f"Week {i} ({(current_monday + timedelta(weeks=i)).strftime('%d %b')} - {(current_monday + timedelta(weeks=i, days=4)).strftime('%d %b')})" for i in range(1, 5)]
        selected_week = st.selectbox("Select Prediction Week:", week_options)
        week_idx = week_options.index(selected_week) + 1

        f_col1, f_col2 = st.columns(2)
        with f_col1:
            wf_f = []
            for _, row in wf_agg.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
                if aht > 0:
                    pred = (row['audit_created_units']/num_weeks) * (1 + (site_growth_val * week_idx))
                    hc = (pred * aht) / (3600 * prod_hours * 5)
                    wf_f.append({"Workflow Name": row['workflow_name'], "Expected Tasks": int(pred), "HC Needed": f"{hc:.2f}", "Staffing Gap": f"{qas_per_site - hc:.2f}"})
            if wf_f:
                df_wf_f = pd.DataFrame(wf_f)
                st.dataframe(df_wf_f.style.map(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)
        with f_col2:
            loc_f = []
            for _, row in loc_agg.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
                if aht > 0:
                    pred = (row['audit_created_units']/num_weeks) * (1 + (site_growth_val * week_idx))
                    hc = (pred * aht) / (3600 * prod_hours * 5)
                    loc_f.append({"Locale": row['locale'], "Expected Tasks": int(pred), "HC Needed": f"{hc:.2f}", "Staffing Gap": f"{qas_per_site - hc:.2f}"})
            if loc_f:
                df_loc_f = pd.DataFrame(loc_f)
                st.dataframe(df_loc_f.style.map(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)
else:
    st.info("Upload files to see filtered active tasks and capacity gaps.")
