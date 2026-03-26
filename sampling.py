import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Team 2 Capacity Planner", layout="wide")

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

st.title("🛡️ Team 2 (Verification) Capacity Planner")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Data Inputs")
    qc_file = st.file_uploader("Upload Volume (Quality Central)", type="csv")
    merc_file = st.file_uploader("Upload AHT (Mercury Metrics)", type="csv")
    
    st.divider()
    t2_current_hc = st.number_input("Current Team 2 Headcount", min_value=0, value=10)
    prod_hours = st.slider("Daily Productive Hours", 4.0, 9.0, 7.5)

# --- DATA PROCESSING ---
if qc_file is not None and merc_file is not None:
    try:
        # Load data safely
        df_qc = pd.read_csv(qc_file)
        df_merc = pd.read_csv(merc_file)

        # Normalize Columns
        df_qc['workflow_name'] = df_qc['workflow_name'].astype(str).str.strip()
        df_merc['Column-4:Transformation Type'] = df_merc['Column-4:Transformation Type'].astype(str).str.strip()
        df_merc['Column-1:Site'] = df_merc['Column-1:Site'].astype(str).str.strip()
        df_merc['Column-2:Locale'] = df_merc['Column-2:Locale'].astype(str).str.strip()

        # 1. Select Site & Map Locales
        all_sites = sorted(df_merc['Column-1:Site'].unique())
        selected_site = st.sidebar.selectbox("Select Site", all_sites)
        site_locales = df_merc[df_merc['Column-1:Site'] == selected_site]['Column-2:Locale'].unique()

        # 2. Select Workflow
        common_wfs = sorted(list(set(df_qc['workflow_name']) & set(df_merc['Column-4:Transformation Type'])))
        wf_choice = st.selectbox("Select Workflow", common_wfs)

        # 3. Calculate Team 2 AHT (95th Percentile Trimmed Mean)
        df_merc['Raw_AHT'] = 3600 * (df_merc['Processed Hours'] + df_merc['Manual Skip Hours']) / df_merc['Processed Units'].replace(0, np.nan)
        aht_data = df_merc[(df_merc['Column-1:Site'] == selected_site) & (df_merc['Column-4:Transformation Type'] == wf_choice)]['Raw_AHT'].dropna()
        
        if not aht_data.empty:
            cleaned_aht = aht_data[aht_data <= aht_data.quantile(0.95)].mean()
        else:
            cleaned_aht = 0.0

        # 4. Analyze Historical Sampling & Volume
        # Filter QC data for this site's locales and the chosen workflow
        wf_qc = df_qc[(df_qc['workflow_name'] == wf_choice) & (df_qc['locale'].isin(site_locales))]
        weekly = wf_qc.groupby('Audit Creation Period Week').agg({
            'production_created_units': 'sum',
            'audit_created_units': 'sum'
        }).reset_index()

        if not weekly.empty:
            avg_prod = weekly['production_created_units'].mean()
            avg_audit = weekly['audit_created_units'].mean()
            hist_sampling = (weekly['audit_created_units'].sum() / weekly['production_created_units'].sum()) * 100
            # Stabilized growth for Team 1 production (0-20%)
            weekly['growth'] = weekly['production_created_units'].pct_change().clip(0, 0.20)
            avg_growth = weekly['growth'].mean() if len(weekly) > 1 else 0.0
        else:
            avg_prod, avg_audit, hist_sampling, avg_growth = 0, 0, 0, 0

        # --- DISPLAY ---
        tab1, tab2 = st.tabs(["📊 Historical Data", "🔮 Team 2 Forecast"])

        with tab1:
            st.subheader(f"Historical Metrics for {selected_site}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Production (Team 1 Output)", f"{avg_prod:,.0f}")
            c2.metric("Historical Sampling %", f"{hist_sampling:.1f}%")
            c3.metric("Team 2 Cleaned AHT", f"{cleaned_aht:.1f}s")

            st.markdown("#### Locale Breakdown (Audit Volume)")
            st.dataframe(wf_qc.groupby('locale')[['production_created_units', 'audit_created_units']].sum(), use_container_width=True)

        with tab2:
            st.subheader("Team 2 Headcount Requirement")
            
            f1, f2 = st.columns(2)
            with f1:
                target_sampling = st.slider("Target Sampling %", 1.0, 50.0, float(hist_sampling) if hist_sampling > 0 else 5.0)
            with f2:
                week_ahead = st.selectbox("Forecast Horizon", [1, 2, 3, 4], format_func=lambda x: f"Week {x}")

            # Calculations
            future_prod = avg_prod * (1 + (avg_growth * week_ahead))
            required_audits = future_prod * (target_sampling / 100)
            
            # Hours needed = (Units * AHT) / 3600
            total_hours = (required_audits * cleaned_aht) / 3600
            hc_needed = total_hours / (prod_hours * 5) # 5-day week

            m1, m2, m3 = st.columns(3)
            m1.metric("Forecasted Audits", f"{required_audits:,.0f}")
            m2.metric("T2 Headcount Needed", f"{hc_needed:.2f}")
            m3.metric("Staffing Gap", f"{hc_needed - t2_current_hc:.2f}")

            if hc_needed > t2_current_hc:
                st.warning(f"⚠️ Team 2 needs approximately **{hc_needed - t2_current_hc:.1f}** additional members.")
            else:
                st.success("✅ Team 2 headcount is sufficient for this workflow.")

    except Exception as e:
        st.error(f"Error processing data: {e}")
else:
    st.info("Please upload both CSV files to begin the planning simulation.")
