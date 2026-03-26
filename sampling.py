import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

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
        try:
            df_m = pd.read_csv(file_mercury)
            df_q = pd.read_csv(file_qc)
            
            # Clean column names (strip spaces)
            df_m.columns = df_m.columns.str.strip()
            df_q.columns = df_q.columns.str.strip()

            # 1. Map Mercury Columns (Site Production)
            # site_col = 'Column-1:Site', locale_col = 'Column-2:Locale', workflow_col = 'Column-4:Transformation Type'
            m_units_col = 'Processed Units'
            m_hours_col = 'Processed Hours'
            m_skip_col = 'Manual Skip Hours'
            
            df_m[m_units_col] = pd.to_numeric(df_m[m_units_col], errors='coerce').fillna(0)
            df_m[m_hours_col] = pd.to_numeric(df_m[m_hours_col], errors='coerce').fillna(0)
            df_m[m_skip_col] = pd.to_numeric(df_m[m_skip_col], errors='coerce').fillna(0)
            
            # AHT Formula: 3600 * (Hours + Skip Hours) / Units
            df_m['Calc_AHT'] = 3600 * (df_m[m_hours_col] + df_m[m_skip_col]) / df_m[m_units_col].replace(0, np.nan)
            df_m['Calc_AHT'] = df_m['Calc_AHT'].fillna(0)
            
            # 2. Map QC Columns (Audited Units)
            # week_col = 'Audit Creation Period Week', audited_units = 'audit_completed_units'
            q_workflow_col = 'workflow_name'
            q_locale_col = 'locale'
            q_units_col = 'audit_completed_units'
            q_week_col = 'Audit Creation Period Week'

            # Standardizing internal names
            df_q['processed_units'] = pd.to_numeric(df_q[q_units_col], errors='coerce').fillna(0)
            df_q['week'] = pd.to_datetime(df_q[q_week_col], errors='coerce')
            
            # 3. Calculate Stable Growth (From QC Week-over-Week)
            weekly_trend = df_q.groupby('week')['processed_units'].sum().sort_index()
            growth_pct = weekly_trend.pct_change().mean()
            stable_growth = growth_pct if not (np.isnan(growth_pct) or np.isinf(growth_pct)) else 0.0529
            
            # 4. Join Files for Sampling %
            m_agg = df_m.groupby(['Column-4:Transformation Type', 'Column-2:Locale', 'Column-1:Site']).agg({
                'Processed Units': 'sum',
                'Calc_AHT': 'mean' 
            }).reset_index()
            
            q_agg = df_q.groupby([q_workflow_col, q_locale_col]).agg({
                'processed_units': 'mean' 
            }).reset_index()
            
            # Merge: QC Workflow to Mercury Transformation Type
            master = pd.merge(
                q_agg, 
                m_agg, 
                left_on=[q_workflow_col, q_locale_col], 
                right_on=['Column-4:Transformation Type', 'Column-2:Locale'], 
                how='left'
            )
            
            # Sampling % = Audited (QC) / Total Site Production (Mercury)
            master['Sampling %'] = (master['processed_units'] / master['Processed Units'].replace(0, np.nan)) * 100
            master['Sampling %'] = master['Sampling %'].fillna(0)
            
            return master, stable_growth
        except Exception as e:
            st.error(f"Data Error: {e}")
            return None, 0.0529
    return None, 0.0529

master_data, growth_rate = load_and_process()

# --- MAIN UI ---
st.title("Strategic Capacity Planner")

if master_data is not None:
    # Sidebar Site Filter
    site_list = master_data['Column-1:Site'].dropna().unique()
    sites = st.sidebar.multiselect("Select Sites", options=site_list, default=site_list)
    df_filtered = master_data[master_data['Column-1:Site'].isin(sites)]
    
    if filter_active:
        df_filtered = df_filtered[df_filtered['Calc_AHT'] > 0]

    # Metrics Row
    col1, col2, col3 = st.columns(3)
    col1.metric("Site Group Growth", f"{growth_rate:.2%}")
    col2.metric("Total Active Locales", len(df_filtered['locale'].unique()) if 'locale' in df_filtered else 0)
    col3.metric("Avg Sampling Rate", f"{df_filtered['Sampling %'].mean():.1f}%")

    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🔮 Forecast Explorer"])

    with tab1:
        st.subheader("Historical 4-Week Baseline")
        display_cols = ['Column-1:Site', 'locale', 'workflow_name', 'processed_units', 'Sampling %', 'Calc_AHT']
        st.dataframe(
            df_filtered[display_cols].rename(columns={
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
        f_col2.metric("Staffing Gap", f"{staffing_gap:.2f}", 
                     delta=f"{staffing_gap:.2f}", 
                     delta_color="normal")
        
        st.dataframe(
            df_filtered[['locale', 'workflow_name', 'Expected Units', 'HC Needed']]
            .style.format({'Expected Units': '{:.0f}', 'HC Needed': '{:.2f}'}),
            use_container_width=True
        )

else:
    st.info("Please upload both Mercury Metrics and Quality Central CSV files to begin.")
