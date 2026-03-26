import streamlit as st
import pandas as pd
import numpy as np

# Page Config - Maintaining your standard UI
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# Custom CSS for the "Executive" look
st.markdown("""
    <style>
    .main { background-color: #f5f7f9; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    [data-testid="stSidebar"] { background-color: #1e293b; color: white; }
    </style>
    """, unsafe_allow_html=True)

# SIDEBAR: Upload & Filters
with st.sidebar:
    st.title("🎛️ Setup")
    
    # Dual Uploaders
    qc_file = st.file_uploader("Upload Volume (Quality Central)", type="csv")
    mercury_file = st.file_uploader("Upload AHT (Mercury Metrics)", type="csv")
    
    st.divider()
    
    # Placeholders for Filters
    site_choice = "Global"
    locale_choice = "All"
    wf_choice = "All"
    target_week = "Week 1"

    if qc_file and mercury_file:
        df_qc = pd.read_csv(qc_file)
        df_merc = pd.read_csv(mercury_file)
        
        # Populate dynamic filters
        sites = sorted(df_merc['Column-1:Site'].dropna().unique())
        site_choice = st.selectbox("Select Site", ["Global"] + sites)
        
        locales = sorted(df_merc['Column-2:Locale'].dropna().unique())
        locale_choice = st.selectbox("Select Locale", ["All"] + locales)
        
        workflows = sorted(df_qc['workflow_name'].dropna().unique())
        wf_choice = st.selectbox("Select Workflow", workflows)
        
        target_week = st.selectbox("Prediction Horizon", ["Week 1", "Week 2", "Week 3", "Week 4"])

# MAIN UI
st.title("Strategic Capacity & Growth Planner")

if qc_file and mercury_file:
    # --- 1. PERFORMANCE CALCULATION (MERCURY) ---
    # Formula: 3600 * (Processed Hours + Manual Skip Hours) / Processed Units
    df_merc['Raw_AHT'] = 3600 * (df_merc['Processed Hours'] + df_merc['Manual Skip Hours']) / df_merc['Processed Units']
    
    # Filter AHT data based on user selection
    aht_mask = (df_merc['Column-4:Transformation Type'] == wf_choice)
    if site_choice != "Global":
        aht_mask &= (df_merc['Column-1:Site'] == site_choice)
    if locale_choice != "All":
        aht_mask &= (df_merc['Column-2:Locale'] == locale_choice)
        
    filtered_aht = df_merc[aht_mask].replace([np.inf, -np.inf], np.nan).dropna(subset=['Raw_AHT'])
    
    if not filtered_aht.empty:
        # 95% Trimmed Mean
        limit = filtered_aht['Raw_AHT'].quantile(0.95)
        cleaned_aht = filtered_aht[filtered_aht['Raw_AHT'] <= limit]['Raw_AHT'].mean()
    else:
        cleaned_aht = 0

    # --- 2. VOLUME CALCULATION (QUALITY CENTRAL) ---
    # Using 'audit_created_units' for volume per workflow
    df_qc_filtered = df_qc[df_qc['workflow_name'] == wf_choice]
    
    # Group by Week to see growth
    weekly_vol = df_qc_filtered.groupby('Audit Creation Period Week')['audit_created_units'].sum().reset_index()
    
    if not weekly_vol.empty:
        baseline_vol = weekly_vol['audit_created_units'].mean()
        # Direct Growth calculation (No cap/floor as requested)
        weekly_vol['growth_rate'] = weekly_vol['audit_created_units'].pct_change()
        avg_growth = weekly_vol['growth_rate'].mean() if len(weekly_vol) > 1 else 0
    else:
        baseline_vol = 0
        avg_growth = 0

    # --- 3. CAPACITY MODEL ---
    week_idx = int(target_week.split()[-1])
    predicted_vol = baseline_vol * (1 + (avg_growth * week_idx))
    
    # HC Calculation (Assume 35 productive hours/week)
    total_sec = predicted_vol * cleaned_aht
    hc_needed = (total_sec / 3600) / 35

    # DISPLAY TABS
    tab1, tab2 = st.tabs(["📊 Historical Performance", "📈 Forecast & Capacity"])

    with tab1:
        st.subheader(f"Historical Audit: {wf_choice}")
        m1, m2, m3 = st.columns(3)
        m1.metric("Direct Growth Trend", f"{avg_growth:.2%}", help="Calculated directly from Quality Central volume")
        m2.metric("Cleaned AHT", f"{cleaned_aht:.1f}s", delta="95% Trimmed")
        m3.metric("Baseline Volume", f"{baseline_vol:,.0f} units")
        
        st.write("### Volume Trend (Quality Central Data)")
        st.line_chart(weekly_vol.set_index('Audit Creation Period Week')['audit_created_units'])

    with tab2:
        st.subheader("Capacity Requirements")
        c1, c2 = st.columns(2)
        
        with c1:
            st.metric("Expected Volume", f"{predicted_vol:,.0f}")
            st.caption(f"Based on {baseline_vol:,.0f} baseline + {avg_growth:.2%} growth.")
            
        with c2:
            st.metric("Headcount Needed", f"{hc_needed:.2f} FTE")
            st.caption(f"Calculated using {cleaned_aht:.1f}s AHT and 35h work week.")

        st.info(f"💡 Strategy: This forecast reflects the sampling changes inherent in the {wf_choice} workflow data.")

else:
    st.warning("Please upload both Quality Central (Volume) and Mercury Metrics (AHT) CSV files to proceed.")