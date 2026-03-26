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

# THE TOGGLE: Strictly enforces Mercury-only task lists
hide_ghosts = st.sidebar.toggle("🚫 Hide Inactive (Mercury Ghosts)", value=True)

qas_per_site = st.sidebar.number_input("Current Team 2 Headcount", min_value=0.1, value=10.0)
prod_hours = st.sidebar.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

if merc_file and qc_file:
    # 1. LOAD & NORMALIZE
    df_m = pd.read_csv(merc_file)
    df_q = pd.read_csv(qc_file)

    for d in [df_m, df_q]:
        for col in d.columns:
            if d[col].dtype == 'object':
                d[col] = d[col].astype(str).str.strip()

    # 2. IDENTIFY MASTER LIST FROM MERCURY
    # We only care about workflows that have actual PROCESSED units in the Metrics file
    df_m['Processed Units'] = pd.to_numeric(df_m['Processed Units'], errors='coerce').fillna(0)
    
    # This is your "Working List"
    working_list = df_m[df_m['Processed Units'] > 0]['Column-4:Transformation Type'].unique()

    # 3. SITE FILTERING (CBG / en_US)
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_sites = st.sidebar.multiselect("Filter Site:", all_sites, default=['CBG'] if 'CBG' in all_sites else all_sites)
    
    f_m_base = df_m[df_m['Column-1:Site'].isin(selected_sites)]
    f_q_base = df_q[df_q['locale'].isin(f_m_base['Column-2:Locale'].unique())]

    # 4. HARD PURGE: If toggle is ON, we delete any workflow from QC that isn't in Mercury's Working List
    if hide_ghosts:
        f_q = f_q_base[f_q_base['workflow_name'].isin(working_list)]
        f_m = f_m_base[f_m_base['Column-4:Transformation Type'].isin(working_list)]
    else:
        f_q = f_q_base
        f_m = f_m_base

    # 5. TASK AUDIT (Sidebar Stats)
    total_qc_tasks = f_q_base['workflow_name'].nunique()
    visible_tasks = f_q['workflow_name'].nunique()
    ghosts_removed = total_qc_tasks - visible_tasks

    with st.sidebar.expander("📝 Data Integrity Audit", expanded=True):
        st.write(f"**Total Tasks in QC:** {total_qc_tasks}")
        st.write(f"**Tasks with Mercury Activity:** {visible_tasks}")
        if hide_ghosts:
            st.error(f"**Ghosts Deleted:** {ghosts_removed}")

    # 6. CALCULATE AHT (Strictly from filtered Mercury)
    f_m['Calc_AHT'] = 3600 * (pd.to_numeric(f_m['Processed Hours'], errors='coerce').fillna(0) + 
                               pd.to_numeric(f_m['Manual Skip Hours'], errors='coerce').fillna(0)) / \
                               f_m['Processed Units'].replace(0, np.nan)

    # 7. GROWTH TREND (Calculated ONLY on the filtered volume)
    batch_cols = ['execution_batch_id', 'workflow_name', 'locale', 'Audit Creation Period Week']
    df_q_dedup = f_q.groupby(batch_cols).agg({'audit_created_units': 'first', 'production_created_units': 'first'}).reset_index()

    def get_growth(data):
        if data.empty: return 0.0
        weekly_sum = data.groupby('Audit Creation Period Week')['audit_created_units'].sum().sort_index()
        u = weekly_sum.values
        if len(u) < 2: return 0.0
        diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
        return np.mean(diffs)

    current_growth = get_growth(df_q_dedup)
    st.sidebar.metric(label="📈 Active Growth Rate", value=f"{current_growth * 100:.2f}%")

    num_weeks = 4
    all_weeks = sorted(df_q['Audit Creation Period Week'].unique(), reverse=True)
    recent_4_weeks = all_weeks[:4]
    qc_baseline = df_q_dedup[df_q_dedup['Audit Creation Period Week'].isin(recent_4_weeks)]

    def get_trimmed_aht(series):
        clean = series.dropna()
        return clean[clean <= clean.quantile(0.95)].mean() if not clean.empty else 0

    def color_gap(val):
        return 'color: red; font-weight: bold' if float(val) < 0 else 'color: green; font-weight: bold'

    # --- TABS ---
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 Future Forecast Explorer"])

    with tab1:
        # LOCALES (TOP)
        st.subheader("📍 Locale Averages")
        loc_agg = qc_baseline.groupby('locale').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
        loc_h = []
        for _, row in loc_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
            s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
            loc_h.append({"Locale": row['locale'], "Avg Weekly Units": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "AHT (Secs)": f"{aht:.1f}"})
        st.dataframe(pd.DataFrame(loc_h), use_container_width=True, hide_index=True)

        st.divider()

        # WORKFLOWS (BOTTOM)
        st.subheader("🛠️ Workflow Averages")
        wf_agg = qc_baseline.groupby('workflow_name').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
        wf_h = []
        for _, row in wf_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
            s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
            wf_h.append({"Workflow Name": row['workflow_name'], "Avg Weekly Units": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "AHT (Secs)": f"{aht:.1f}"})
        st.dataframe(pd.DataFrame(wf_h), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Capacity Forecast Explorer")
        week_options = ["Week 1", "Week 2", "Week 3", "Week 4"]
        selected_week = st.selectbox("Select Prediction Week:", week_options)
        week_idx = week_options.index(selected_week) + 1

        # LOCALES (TOP)
        st.markdown("#### 📍 Locale Forecast")
        loc_f = []
        for _, row in loc_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
            pred = (row['audit_created_units']/num_weeks) * (1 + (current_growth * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            loc_f.append({"Locale": row['locale'], "Expected Units": int(pred), "HC Needed": f"{hc:.2f}", "Staffing Gap": f"{qas_per_site - hc:.2f}"})
        st.dataframe(pd.DataFrame(loc_f).style.map(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)

        st.divider()

        # WORKFLOWS (BOTTOM)
        st.markdown("#### 🛠️ Workflow Forecast")
        wf_f = []
        for _, row in wf_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
            pred = (row['audit_created_units']/num_weeks) * (1 + (current_growth * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            wf_f.append({"Workflow Name": row['workflow_name'], "Expected Units": int(pred), "HC Needed": f"{hc:.2f}", "Staffing Gap": f"{qas_per_site - hc:.2f}"})
        st.dataframe(pd.DataFrame(wf_f).style.map(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)
else:
    st.info("Upload files. The logic now strictly cross-references Mercury activity to purge ghost workflows.")
