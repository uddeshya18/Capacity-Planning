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

# NEW: Ghost Task Toggle
hide_ghosts = st.sidebar.toggle("🚫 Hide Inactive (Ghost) Tasks", value=True)

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

    # 2. CALC AHT (Mercury)
    df_m['Calc_AHT'] = 3600 * (pd.to_numeric(df_m['Processed Hours'], errors='coerce').fillna(0) + 
                               pd.to_numeric(df_m['Manual Skip Hours'], errors='coerce').fillna(0)) / \
                               pd.to_numeric(df_m['Processed Units'], errors='coerce').replace(0, np.nan)

    # 3. IDENTIFY ACTIVE TASKS (Last 2 weeks in QC)
    all_weeks = sorted(df_q['Audit Creation Period Week'].unique(), reverse=True)
    recent_2_weeks = all_weeks[:2]
    active_wf = df_q[df_q['Audit Creation Period Week'].isin(recent_2_weeks)]['workflow_name'].unique()

    # 4. SITE FILTERING
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_sites = st.sidebar.multiselect("Filter Site:", all_sites, default=['CBG'] if 'CBG' in all_sites else all_sites)
    
    f_m = df_m[df_m['Column-1:Site'].isin(selected_sites)]
    site_locales = f_m['Column-2:Locale'].unique()
    f_q = df_q[df_q['locale'].isin(site_locales)]

    # 5. DEDUPLICATION (Batch Level)
    batch_cols = ['execution_batch_id', 'workflow_name', 'locale', 'Audit Creation Period Week']
    df_q_dedup = f_q.groupby(batch_cols).agg({'audit_created_units': 'first', 'production_created_units': 'first'}).reset_index()

    # 6. GROWTH TREND
    site_growth_val = 0.0
    if not df_q_dedup.empty:
        weekly_sum = df_q_dedup.groupby('Audit Creation Period Week')['audit_created_units'].sum().sort_index()
        u = weekly_sum.values
        if len(u) > 1:
            diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
            site_growth_val = np.mean(diffs) if diffs else 0.0

    st.sidebar.metric(label="📈 Overall Growth Rate", value=f"{site_growth_val * 100:.2f}%")

    # 7. MERGE PERFORMANCE (Mercury) WITH VOLUME (QC)
    # Group Mercury tasks first
    merc_grouped = f_m.groupby(['Column-4:Transformation Type', 'Column-2:Locale']).agg({
        'Calc_AHT': lambda x: x[x <= x.quantile(0.95)].mean()
    }).reset_index()

    # Group QC baseline (Avg of last 4 weeks)
    qc_baseline = df_q_dedup[df_q_dedup['Audit Creation Period Week'].isin(all_weeks[:4])]
    qc_agg = qc_baseline.groupby(['workflow_name', 'locale']).agg({
        'audit_created_units': 'sum',
        'production_created_units': 'sum'
    }).reset_index()

    # Merge
    final_df = pd.merge(
        merc_grouped, 
        qc_agg, 
        left_on=['Column-4:Transformation Type', 'Column-2:Locale'], 
        right_on=['workflow_name', 'locale'], 
        how='inner' # Only show tasks that exist in both files
    )

    # Apply Ghost Filter Toggle
    if hide_ghosts:
        final_df = final_df[final_df['Column-4:Transformation Type'].isin(active_wf)]

    # --- TABS ---
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 Future Forecast Explorer"])

    with tab1:
        st.subheader("Historical Performance Match")
        hist_table = []
        for _, row in final_df.iterrows():
            avg_weekly = row['audit_created_units'] / 4
            s_pct = (row['audit_created_units'] / row['production_created_units'] * 100) if row['production_created_units'] > 0 else 0
            hist_table.append({
                "Transformation Type": row['Column-4:Transformation Type'],
                "Locale": row['Column-2:Locale'],
                "Avg Weekly Tasks": int(avg_weekly),
                "Sampling %": f"{s_pct:.1f}%",
                "AHT (Secs)": f"{row['Calc_AHT']:.1f}"
            })
        st.dataframe(pd.DataFrame(hist_table), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Forecast vs Staffing Capacity")
        week_options = [f"Week {i}" for i in range(1, 5)]
        selected_week = st.selectbox("Select Prediction Week:", week_options)
        week_idx = week_options.index(selected_week) + 1

        f_table = []
        for _, row in final_df.iterrows():
            avg_weekly = row['audit_created_units'] / 4
            pred_tasks = avg_weekly * (1 + (site_growth_val * week_idx))
            hc_req = (pred_tasks * row['Calc_AHT']) / (3600 * prod_hours * 5)
            
            f_table.append({
                "Transformation Type": row['Column-4:Transformation Type'],
                "Locale": row['Column-2:Locale'],
                "Expected Tasks": int(pred_tasks),
                "HC Needed": f"{hc_req:.2f}",
                "Staffing Gap": f"{qas_per_site - hc_req:.2f}"
            })
        
        if f_table:
            df_f = pd.DataFrame(f_table)
            def color_gap(val):
                return 'color: red; font-weight: bold' if float(val) < 0 else 'color: green; font-weight: bold'
            st.dataframe(df_f.style.map(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)
else:
    st.info("Upload files to verify the CBG en_US task list.")
