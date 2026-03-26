import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- UI THEME (Standardized as per your request) ---
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

# --- SIDEBAR: GLOBAL CONTROLS ---
st.sidebar.header("⚙️ Global Settings")
merc_file = st.sidebar.file_uploader("Upload Mercury Metrics (AHT)", type="csv")
qc_file = st.sidebar.file_uploader("Upload Quality Central (Volume/Sampling)", type="csv")

qas_per_site = st.sidebar.number_input("Current QAs (Actual)", min_value=1, value=10)
prod_hours = st.sidebar.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

def get_monday(d):
    return d - timedelta(days=d.weekday())

current_monday = get_monday(datetime.now())

if merc_file and qc_file:
    # 1. LOAD & CLEAN DATA
    df_m = pd.read_csv(merc_file)
    df_q = pd.read_csv(qc_file)

    # Clean strings to fix visibility issues
    for d in [df_m, df_q]:
        for col in d.columns:
            if d[col].dtype == 'object':
                d[col] = d[col].astype(str).str.strip()

    # Column Mapping for Mercury
    m_cols = df_m.columns.tolist()
    idx_site = next((i for i, c in enumerate(m_cols) if "site" in c.lower()), 0)
    idx_loc = next((i for i, c in enumerate(m_cols) if "locale" in c.lower()), 1)
    idx_wf = next((i for i, c in enumerate(m_cols) if "transformation" in c.lower() or "workflow" in c.lower()), 3)
    
    # CALCULATE MANUAL AHT (Fixes the "Nothing in Cleaned AHT" issue)
    df_m['Raw_AHT'] = 3600 * (df_m['Processed Hours'] + df_m['Manual Skip Hours']) / df_m['Processed Units'].replace(0, np.nan)
    df_m = df_m.dropna(subset=['Raw_AHT'])

    # 2. GROWTH CALCULATION (UNCAPPED)
    # Using Quality Central 'audit_created_units' for Sampling Growth
    all_sites = sorted(df_m.iloc[:, idx_site].unique())
    selected_sites = st.sidebar.multiselect("Filter Site:", all_sites, default=all_sites)
    
    # Map Locales to Sites
    site_locales = df_m[df_m.iloc[:, idx_site].isin(selected_sites)].iloc[:, idx_loc].unique()
    df_q_filtered = df_q[df_q['locale'].isin(site_locales)]
    
    site_growth_val = 0.0
    if not df_q_filtered.empty:
        site_weekly = df_q_filtered.groupby('Audit Creation Period Week')['audit_created_units'].sum().reset_index()
        u = site_weekly['audit_created_units'].values
        if len(u) > 1:
            # RAW PERCENTAGE CHANGE (No Cap)
            diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
            site_growth_val = np.mean(diffs) if diffs else 0.0

    st.sidebar.metric(label="📈 Estimated Growth (Uncapped)", value=f"{site_growth_val * 100:.2f}%")
    st.sidebar.divider()

    # 3. FILTERING
    all_locales = sorted(site_locales)
    selected_locales = st.sidebar.multiselect("Filter Locale:", all_locales, default=all_locales)
    
    # Filtered Dataframes
    f_m = df_m[(df_m.iloc[:, idx_site].isin(selected_sites)) & (df_m.iloc[:, idx_loc].isin(selected_locales))]
    f_q = df_q[df_q['locale'].isin(selected_locales)]

    def get_cleaned_aht(group):
        if group.empty: return 0.0
        # 95th Percentile Trimmed Mean
        q95 = group.quantile(0.95)
        return group[group <= q95].mean()

    # 4. TABS
    tab1, tab2 = st.tabs(["📋 Historical Performance", "🚀 Capacity Forecast"])

    with tab1:
        st.subheader("Historical Verification Summary")
        
        # Site/Locale Summary with Sampling %
        summary_data = []
        for loc in selected_locales:
            m_loc = f_m[f_m.iloc[:, idx_loc] == loc]
            q_loc = f_q[f_q['locale'] == loc]
            
            aht_val = get_cleaned_aht(m_loc['Raw_AHT'])
            # Sampling % = Audits / Production
            prod = q_loc['production_created_units'].sum()
            audits = q_loc['audit_created_units'].sum()
            samp_pct = (audits / prod * 100) if prod > 0 else 0
            
            summary_data.append({
                "Locale": loc,
                "Cleaned AHT (s)": f"{aht_val:.1f}",
                "Sampling %": f"{samp_pct:.1f}%",
                "Avg Weekly Units": int(audits / len(df_q['Audit Creation Period Week'].unique())) if not df_q.empty else 0
            })
        st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)

        # Workflow Breakdown
        st.markdown("### 🛠️ Workflow Details (Historical)")
        wf_stats = []
        for wf in sorted(f_m.iloc[:, idx_wf].unique()):
            wf_m = f_m[f_m.iloc[:, idx_wf] == wf]
            wf_q = f_q[f_q['workflow_name'] == wf]
            
            wf_aht = get_cleaned_aht(wf_m['Raw_AHT'])
            wf_units = wf_q['audit_created_units'].sum()
            
            wf_stats.append({
                "Transformation Type": wf,
                "Cleaned AHT (s)": f"{wf_aht:.1f}",
                "Total Audits": int(wf_units)
            })
        st.dataframe(pd.DataFrame(wf_stats), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Future Capacity Prediction")
        
        week_options = [f"Week {i+1}" for i in range(4)]
        selected_week = st.selectbox("Select Forecast Horizon:", week_options)
        week_idx = week_options.index(selected_week) + 1
        
        forecast_results = []
        for loc in selected_locales:
            m_loc = f_m[f_m.iloc[:, idx_loc] == loc]
            q_loc = f_q[f_q['locale'] == loc]
            
            base_units = q_loc['audit_created_units'].sum() / len(df_q['Audit Creation Period Week'].unique())
            pred_vol = base_units * (1 + (site_growth_val * week_idx))
            aht_val = get_cleaned_aht(m_loc['Raw_AHT'])
            
            req_hours = (pred_vol * aht_val) / 3600
            hc_needed = req_hours / (prod_hours * 5)
            
            forecast_results.append({
                "Locale": loc, 
                "Exp. Volume": int(pred_vol), 
                "Utilization %": f"{(hc_needed / qas_per_site * 100):.1f}%" if qas_per_site > 0 else "0%",
                "HC Needed": f"{hc_needed:.2f}",
                "Staffing Gap": f"{qas_per_site - hc_needed:.2f}"
            })
        st.dataframe(pd.DataFrame(forecast_results), use_container_width=True, hide_index=True)

else:
    st.info("Please upload both Mercury Metrics and Quality Central CSV files to proceed.")
