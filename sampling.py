import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- SET PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- CUSTOM CSS FOR UI CONSISTENCY ---
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    [data-testid="stSidebar"] { background-color: #ffffff; border-right: 1px solid #e6e9ef; }
    </style>
    """, unsafe_allow_html=True)

# --- SIDEBAR: CONTROLS & UPLOADS ---
with st.sidebar:
    st.header("⚙️ Configuration")
    
    file_mercury = st.file_uploader("Upload Mercury Metrics (CSV)", type="csv")
    file_qc = st.file_uploader("Upload Quality Central (CSV)", type="csv")
    
    st.divider()
    
    qa_available = st.number_input("QA Available for the Week", min_value=1, value=20)
    prod_hours = st.slider("Daily Productive Hours", 5.0, 9.0, 7.5, 0.5)
    
    st.divider()
    filter_active = st.checkbox("Filter Active Workflows Only (AHT > 0)", value=True)

# --- DATA PROCESSING ENGINE ---
def load_and_process():
    if file_mercury and file_qc:
        # Load Files
        df_m = pd.read_csv(file_mercury)
        df_q = pd.read_csv(file_qc)
        
        # 1. Standardize Mercury (Total Site Production)
        df_m['Processed Units'] = pd.to_numeric(df_m['Processed Units'], errors='coerce').fillna(0)
        df_m['Processed Hours'] = pd.to_numeric(df_m['Processed Hours'], errors='coerce').fillna(0)
        df_m['Manual Skip Hours'] = pd.to_numeric(df_m['Manual Skip Hours'], errors='coerce').fillna(0)
        
        # AHT Formula: 3600 * (Hours + Skip Hours) / Units
        df_m['Calc_AHT'] = 3600 * (df_m['Processed Hours'] + df_m['Manual Skip Hours']) / df_m['Processed Units'].replace(0, np.nan)
        df_m['Calc_AHT'] = df_m['Calc_AHT'].fillna(0)
        
        # 2. Standardize QC (Audited Units)
        df_q['processed_units'] = pd.to_numeric(df_q['processed_units'], errors='coerce').fillna(0)
        df_q['week'] = pd.to_datetime(df_q['week'], errors='coerce')
        
        # 3. Calculate Stable Growth (From QC Week-over-Week)
        weekly_trend = df_q.groupby('week')['processed_units'].sum().sort_index()
        growth_pct = weekly_trend.pct_change().mean()
        stable_growth = growth_pct if not np.isnan(growth_pct) else 0.0529
        
        # 4. Join Files for Sampling % and Mapping
        # Aggregate Mercury by Workflow/Locale
        m_agg = df_m.groupby(['Workflow Name', 'Column-2:Locale', 'Column-1:Site']).agg({
            'Processed Units': 'sum',
            'Calc_AHT': 'mean' # Average AHT over 4 weeks
        }).reset_index()
        
        # Aggregate QC by Workflow/Locale
        q_agg = df_q.groupby(['workflow_name', 'locale']).agg({
            'processed_units': 'mean' # Avg Audited units per week
        }).reset_index()
        
        # Merge (Audit data compared to Site Production)
        master = pd.merge(
            q_agg, 
            m_agg, 
            left_on=['workflow_name', 'locale'], 
            right_on=['Workflow Name', 'Column-2:Locale'], 
            how='left'
        )
        
        # Sampling % = Audited / Production
        master['Sampling %'] = (master['processed_units'] / master['Processed Units'].replace(0, np.nan)) * 100
        master['Sampling %'] = master['Sampling %'].fillna(0)
        
        return master, stable_growth
    return None, 0.0529

master_data, growth_rate = load_and_process()

# --- MAIN UI ---
st.title("Strategic Capacity Planner")

if master_data is not None:
    # Sidebar Site Filter
    sites = st.sidebar.multiselect("Select Sites", options=master_data['Column-1:Site'].unique(), default=master_data['Column-1:Site'].unique())
    df_filtered = master_data[master_data['Column-1:Site'].isin(sites)]
    
    if filter_active:
        df_filtered = df_filtered[df_filtered['Calc_AHT'] > 0]

    # Metrics Row
    col1, col2, col3 = st.columns(3)
    col1.metric("Site Group Growth", f"{growth_rate:.2%}")
    col2.metric("Total Active Locales", len(df_filtered['locale'].unique()))
    col3.metric("Avg Sampling Rate", f"{df_filtered['Sampling %'].mean():.1f}%")

    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🔮 Forecast Explorer"])

    with tab1:
        st.subheader("Historical 4-Week Baseline")
        st.dataframe(
            df_filtered[['Column-1:Site', 'locale', 'workflow_name', 'processed_units', 'Sampling %', 'Calc_AHT']]
            .rename(columns={
                'processed_units': 'Avg Weekly Audits',
                'Calc_AHT': 'AHT (Secs)'
            }), 
            use_container_width=True
        )

    with tab2:
        st.subheader("Capacity Forecast")
        target_week = st.selectbox("Select Forecast Week", ["Week 1", "Week 2", "Week 3", "Week 4"])
        week_num = int(target_week.split()[-1])
        
        # Projected Math
        df_filtered['Expected Units'] = df_filtered['processed_units'] * (1 + growth_rate)**week_num
        df_filtered['Hours Needed'] = (df_filtered['Expected Units'] * df_filtered['Calc_AHT']) / 3600
        df_filtered['HC Needed'] = df_filtered['Hours Needed'] / (prod_hours * 5)
        
        total_hc_needed = df_filtered['HC Needed'].sum()
        staffing_gap = qa_available - total_hc_needed
        
        # Forecast Summary
        f_col1, f_col2 = st.columns(2)
        f_col1.metric("Total HC Needed", f"{total_hc_needed:.2f}")
        f_col2.metric("Staffing Gap", f"{staffing_gap:.2f}", delta=f"{staffing_gap:.2f}", delta_color="normal")
        
        st.dataframe(
            df_filtered[['locale', 'workflow_name', 'Expected Units', 'HC Needed']]
            .style.format({'Expected Units': '{:.0f}', 'HC Needed': '{:.2f}'}),
            use_container_width=True
        )

else:
    st.info("Please upload both Mercury Metrics and Quality Central CSV files to begin.")
