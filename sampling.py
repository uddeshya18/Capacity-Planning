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

hide_ghosts = st.sidebar.toggle("🚫 Hide Ghosts (AHT=0 & HC=0)", value=True)

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

    # 2. SITE & AUTO-LOCALE
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_site = st.sidebar.selectbox("Select Site:", all_sites, index=all_sites.index('CBG') if 'CBG' in all_sites else 0)
    site_locales = df_m[df_m['Column-1:Site'] == selected_site]['Column-2:Locale'].unique()
    
    # Base Data (Before Ghost Filtering)
    f_m_base = df_m[df_m['Column-1:Site'] == selected_site]
    f_q_base = df_q[df_q['locale'].isin(site_locales)]

    # 3. CALCULATE STABLE GROWTH (CRITICAL FIX)
    # We calculate growth on the TOTAL site data BEFORE hiding ghosts.
    # This keeps the growth at 5.29% instead of spiking to 32%.
    batch_cols = ['execution_batch_id', 'workflow_name', 'locale', 'Audit Creation Period Week']
    df_q_all_dedup = f_q_base.groupby(batch_cols).agg({'audit_created_units': 'first'}).reset_index()

    def get_stable_growth(data):
        if data.empty: return 0.0
        weekly_sum = data.groupby('Audit Creation Period Week')['audit_created_units'].sum().sort_index()
        u = weekly_sum.values
        if len(u) < 2: return 0.0
        diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
        return np.mean(diffs)

    # This rate remains the same regardless of the toggle
    stable_site_growth = get_stable_growth(df_q_all_dedup)
    st.sidebar.metric(label=f"📈 Stable Site Growth ({selected_site})", value=f"{stable_site_growth * 100:.2f}%")

    # 4. GHOST DETECTION
    f_m_base['Processed Units'] = pd.to_numeric(f_m_base['Processed Units'], errors='coerce').fillna(0)
    f_m_base['Processed Hours'] = pd.to_numeric(f_m_base['Processed Hours'], errors='coerce').fillna(0)
    f_m_base['Calc_AHT'] = 3600 * (f_m_base['Processed Hours'] + 
                                   pd.to_numeric(f_m_base['Manual Skip Hours'], errors='coerce').fillna(0)) / \
                                   f_m_base['Processed Units'].replace(0, np.nan)
    f_m_base['Calc_AHT'] = f_m_base['Calc_AHT'].fillna(0)

    # Active = AHT > 0
    real_workflows = f_m_base[f_m_base['Calc_AHT'] > 0]['Column-4:Transformation Type'].unique()

    # 5. TASK INVENTORY AUDIT
    total_tasks = f_q_base['workflow_name'].nunique()
    active_tasks = len([x for x in f_q_base['workflow_name'].unique() if x in real_workflows])
    ghosts_found = total_tasks - active_tasks

    with st.sidebar.expander("📝 Site Data Summary", expanded=True):
        st.write(f"**Total Tasks:** {total_tasks}")
        if hide_ghosts:
            st.success(f"**Showing Active:** {active_tasks}")
            st.error(f"**Hidden Ghosts:** {ghosts_found}")

    # 6. APPLY FILTERING TO DATA LISTS
    if hide_ghosts:
        f_q = f_q_base[f_q_base['workflow_name'].isin(real_workflows)]
        f_m = f_m_base[f_m_base['Column-4:Transformation Type'].isin(real_workflows)]
    else:
        f_q = f_q_base
        f_m = f_m_base

    # 7. BASELINE PREP
    df_q_final_dedup = f_q.groupby(batch_cols).agg({'audit_created_units': 'first', 'production_created_units': 'first'}).reset_index()
    num_weeks = 4
    all_weeks = sorted(df_q['Audit Creation Period Week'].unique(), reverse=True)
    recent_4_weeks = all_weeks[:4]
    qc_baseline = df_q_final_dedup[df_q_final_dedup['Audit Creation Period Week'].isin(recent_4_weeks)]

    def get_trimmed_aht(series):
        clean = series.dropna()
        return clean[clean <= clean.quantile(0.95)].mean() if not clean.empty else 0

    def color_gap(val):
        try:
            return 'color: red; font-weight: bold' if float(val) < 0 else 'color: green; font-weight: bold'
        except: return ''

    # --- TABS ---
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 Future Forecast Explorer"])

    with tab1:
        st.subheader(f"Historical Performance: {selected_site}")
        # LOCALE TABLE
        loc_agg = qc_baseline.groupby('locale').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
        loc_h = []
        for _, row in loc_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
            s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
            loc_h.append({"Locale": row['locale'], "Avg Weekly Units": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "AHT (Secs)": f"{aht:.1f}"})
        st.dataframe(pd.DataFrame(loc_h), use_container_width=True, hide_index=True)

        st.divider()

        # WORKFLOW TABLE
        wf_agg = qc_baseline.groupby('workflow_name').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
        wf_h = []
        for _, row in wf_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
            s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
            wf_h.append({"Workflow Name": row['workflow_name'], "Avg Weekly Units": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "AHT (Secs)": f"{aht:.1f}"})
        st.dataframe(pd.DataFrame(wf_h), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader(f"Capacity Forecast: {selected_site}")
        week_options = ["Week 1", "Week 2", "Week 3", "Week 4"]
        selected_week = st.selectbox("Select Prediction Week:", week_options)
        week_idx = week_options.index(selected_week) + 1

        # FORECASTS (Using the STABLE growth)
        st.markdown("#### 📍 Locale Forecast")
        loc_f = []
        for _, row in loc_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
            # Calculation uses the locked site growth
            pred = (row['audit_created_units']/num_weeks) * (1 + (stable_site_growth * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            loc_f.append({"Locale": row['locale'], "Expected Units": int(pred), "HC Needed": f"{hc:.2f}", "Staffing Gap": f"{qas_per_site - hc:.2f}"})
        st.dataframe(pd.DataFrame(loc_f).style.applymap(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)

        st.divider()

        st.markdown("#### 🛠️ Workflow Forecast")
        wf_f = []
        for _, row in wf_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
            pred = (row['audit_created_units']/num_weeks) * (1 + (stable_site_growth * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            wf_f.append({"Workflow Name": row['workflow_name'], "Expected Units": int(pred), "HC Needed": f"{hc:.2f}", "Staffing Gap": f"{qas_per_site - hc:.2f}"})
        st.dataframe(pd.DataFrame(wf_f).style.applymap(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)
else:
    st.info("Upload files. The Stable Growth logic prevents the 32% jump when hiding ghosts.")
