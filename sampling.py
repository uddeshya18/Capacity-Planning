import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- UI THEME ---
st.markdown("""
    <style>
    .stApp { background-color: #f8fafc !important; }
    div[data-testid="metric-container"] {
        background-color: #ffffff; border: 1px solid #e2e8f0;
        padding: 20px; border-radius: 12px;
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

# TOGGLE
hide_ghosts = st.sidebar.toggle("🚫 Hide Inactive (Ghost) Tasks", value=True)

qas_per_site = st.sidebar.number_input("Current Team 2 Headcount", min_value=0.1, value=10.0)
prod_hours = st.sidebar.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

if merc_file and qc_file:
    # 1. LOAD
    df_m = pd.read_csv(merc_file)
    df_q = pd.read_csv(qc_file)

    for d in [df_m, df_q]:
        for col in d.columns:
            if d[col].dtype == 'object':
                d[col] = d[col].astype(str).str.strip()

    # 2. CALC AHT (Mercury)
    df_m['Calc_AHT'] = 3600 * (pd.to_numeric(df_m['Processed Hours'], errors='coerce').fillna(0) + 
                               pd.to_numeric(df_m['Manual Skip Hours'], errors='coerce').fillna(0)) / \
                               pd.to_numeric(df_m['Processed Units'], errors='coerce').replace(0, np.nan)

    # 3. IDENTIFY ACTIVE vs GHOST
    all_weeks = sorted(df_q['Audit Creation Period Week'].unique(), reverse=True)
    recent_2_weeks = all_weeks[:2]
    active_wf = df_q[df_q['Audit Creation Period Week'].isin(recent_2_weeks)]['workflow_name'].unique()
    active_loc = df_q[df_q['Audit Creation Period Week'].isin(recent_2_weeks)]['locale'].unique()

    # 4. SITE FILTERING
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_sites = st.sidebar.multiselect("Filter Site:", all_sites, default=['CBG'] if 'CBG' in all_sites else all_sites)
    f_m = df_m[df_m['Column-1:Site'].isin(selected_sites)]
    f_q = df_q[df_q['locale'].isin(f_m['Column-2:Locale'].unique())]

    # 5. DEDUPLICATION & STABLE GROWTH
    # IMPORTANT: Growth is calculated ONCE on all filtered data to keep the rate stable.
    batch_cols = ['execution_batch_id', 'workflow_name', 'locale', 'Audit Creation Period Week']
    df_q_dedup = f_q.groupby(batch_cols).agg({'audit_created_units': 'first', 'production_created_units': 'first'}).reset_index()

    def get_stable_growth(data):
        if data.empty: return 0.0
        weekly_sum = data.groupby('Audit Creation Period Week')['audit_created_units'].sum().sort_index()
        u = weekly_sum.values
        if len(u) < 2: return 0.0
        diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
        return np.mean(diffs)

    # Lock the growth rate before any ghosts are hidden
    global_growth_rate = get_stable_growth(df_q_dedup)
    st.sidebar.metric(label="📈 Locked Growth Rate", value=f"{global_growth_rate * 100:.2f}%")

    # 6. BASELINE (Last 4 Weeks)
    num_weeks = 4
    recent_4_weeks = all_weeks[:4]
    qc_baseline = df_q_dedup[df_q_dedup['Audit Creation Period Week'].isin(recent_4_weeks)]

    # 7. APPLY GHOST FILTER TO TABLES ONLY
    # This removes the tasks from the list but uses the "Locked" growth rate so volume doesn't spike.
    if hide_ghosts:
        qc_baseline = qc_baseline[qc_baseline['workflow_name'].isin(active_wf) & qc_baseline['locale'].isin(active_loc)]
        f_m = f_m[f_m['Column-4:Transformation Type'].isin(active_wf) & f_m['Column-2:Locale'].isin(active_loc)]

    def get_trimmed_aht(series):
        clean = series.dropna()
        return clean[clean <= clean.quantile(0.95)].mean() if not clean.empty else 0

    def color_gap(val):
        return 'color: red; font-weight: bold' if float(val) < 0 else 'color: green; font-weight: bold'

    # --- TABS ---
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 Future Forecast Explorer"])

    with tab1:
        st.subheader("Historical Weekly Averages")
        # LOCALES TOP
        st.markdown("#### 📍 Locale Average")
        loc_agg = qc_baseline.groupby('locale').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
        loc_h = []
        for _, row in loc_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
            s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
            loc_h.append({"Locale": row['locale'], "Avg Weekly Tasks": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "AHT (Secs)": f"{aht:.1f}"})
        st.dataframe(pd.DataFrame(loc_h), use_container_width=True, hide_index=True)

        # WORKFLOWS BOTTOM
        st.markdown("#### 🛠️ Workflow Average")
        wf_agg = qc_baseline.groupby('workflow_name').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
        wf_h = []
        for _, row in wf_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
            s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
            wf_h.append({"Workflow Name": row['workflow_name'], "Avg Weekly Tasks": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "AHT (Secs)": f"{aht:.1f}"})
        st.dataframe(pd.DataFrame(wf_h), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Capacity Forecast Explorer")
        week_options = ["Week 1", "Week 2", "Week 3", "Week 4"]
        selected_week = st.selectbox("Select Prediction Week:", week_options)
        week_idx = week_options.index(selected_week) + 1

        # LOCALES TOP
        st.markdown("#### 📍 Locale Forecast")
        loc_f = []
        for _, row in loc_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
            # We use the LOCKED global_growth_rate here
            pred = (row['audit_created_units']/num_weeks) * (1 + (global_growth_rate * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            loc_f.append({"Locale": row['locale'], "Expected Tasks": int(pred), "HC Needed": f"{hc:.2f}", "Staffing Gap": f"{qas_per_site - hc:.2f}"})
        st.dataframe(pd.DataFrame(loc_f).style.map(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)

        # WORKFLOWS BOTTOM
        st.markdown("#### 🛠️ Workflow Forecast")
        wf_f = []
        for _, row in wf_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
            pred = (row['audit_created_units']/num_weeks) * (1 + (global_growth_rate * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            wf_f.append({"Workflow Name": row['workflow_name'], "Expected Tasks": int(pred), "HC Needed": f"{hc:.2f}", "Staffing Gap": f"{qas_per_site - hc:.2f}"})
        st.dataframe(pd.DataFrame(wf_f).style.map(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)
else:
    st.info("Upload files. The 'Locked Growth' logic prevents the volume spike when hiding ghost tasks.")
