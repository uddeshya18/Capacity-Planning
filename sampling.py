import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Team Capacity Simulator", layout="wide")

# --- UI THEME (Unified Slate/White) ---
st.markdown("""
    <style>
    .stApp, [data-testid="stSidebar"] { background-color: #f8fafc !important; }
    div[data-testid="metric-container"] {
        background-color: #ffffff; border: 1px solid #e2e8f0;
        padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #f1f5f9; border-radius: 8px 8px 0 0; padding: 10px 20px;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🛡️ Team Verification Capacity Simulator")

# --- SIDEBAR: SITE & TEAM CONFIGURATION ---
with st.sidebar:
    st.header("📂 Data Source")
    qc_file = st.file_uploader("Upload Volume (Quality Central)", type="csv")
    merc_file = st.file_uploader("Upload AHT (Mercury Metrics)", type="csv")
    
    st.divider()
    
    if merc_file:
        df_site_lookup = pd.read_csv(merc_file)
        sites = sorted(df_site_lookup['Column-1:Site'].astype(str).unique())
        selected_site = st.selectbox("📍 Select Site for Planning:", sites)
        
        st.subheader(f"👥 Site Headcount: {selected_site}")
        team1_size = st.number_input("Team 1 Size (Production)", min_value=1, value=100)
        team2_size = st.number_input("Team 2 Size (Verification)", min_value=0, value=10)
        prod_hours = st.slider("Productive Hours/Day", 4.0, 9.0, 7.5)

if qc_file and merc_file:
    # 1. DATA PREP & MAPPING
    df_qc = pd.read_csv(qc_file)
    df_merc = pd.read_csv(merc_file)

    # Normalize Strings
    df_qc['workflow_name'] = df_qc['workflow_name'].astype(str).str.strip()
    df_merc['Column-4:Transformation Type'] = df_merc['Column-4:Transformation Type'].astype(str).str.strip()
    df_merc['Column-1:Site'] = df_merc['Column-1:Site'].astype(str).str.strip()
    df_merc['Column-2:Locale'] = df_merc['Column-2:Locale'].astype(str).str.strip()

    # Link Site (Mercury) to Locales (QC)
    site_locales = df_merc[df_merc['Column-1:Site'] == selected_site]['Column-2:Locale'].unique()
    
    # Calculate AHT (Mercury)
    df_merc['Raw_AHT'] = 3600 * (df_merc['Processed Hours'] + df_merc['Manual Skip Hours']) / df_merc['Processed Units'].replace(0, np.nan)
    
    # Filter QC by site's locales
    df_qc_site = df_qc[df_qc['locale'].isin(site_locales)]
    
    # Workflow Filter
    common_wfs = sorted(list(set(df_qc_site['workflow_name']) & set(df_merc['Column-4:Transformation Type'])))
    wf_choice = st.selectbox("🛠️ Select Workflow to Analyze:", common_wfs)

    # 2. HISTORICAL ANALYSIS (TEAM 1 VS TEAM 2)
    wf_data = df_qc_site[df_qc_site['workflow_name'] == wf_choice]
    weekly = wf_data.groupby('Audit Creation Period Week').agg({
        'production_created_units': 'sum',
        'audit_created_units': 'sum'
    }).reset_index()

    if not weekly.empty:
        # Team 1 Metrics (Production)
        avg_prod_vol = weekly['production_created_units'].mean()
        # Team 2 Metrics (Verification)
        avg_audit_vol = weekly['audit_created_units'].mean()
        # Sampling Strategy
        hist_sampling_rate = (weekly['audit_created_units'].sum() / weekly['production_created_units'].sum()) * 100
        # Growth (Stabilized 0-20%)
        weekly['growth'] = weekly['production_created_units'].pct_change().clip(0, 0.20)
        avg_growth = weekly['growth'].mean() if len(weekly) > 1 else 0.0
    else:
        avg_prod_vol, avg_audit_vol, hist_sampling_rate, avg_growth = 0, 0, 0, 0

    # 3. PERFORMANCE CALCULATION (TEAM 2 AHT)
    aht_mask = (df_merc['Column-1:Site'] == selected_site) & (df_merc['Column-4:Transformation Type'] == wf_choice)
    aht_series = df_merc[aht_mask]['Raw_AHT'].dropna()
    # Trimmed Mean 95th Percentile
    cleaned_aht = aht_series[aht_series <= aht_series.quantile(0.95)].mean() if not aht_series.empty else 0.0

    # 4. DASHBOARD TABS
    tab1, tab2 = st.tabs(["📊 Historical Team Performance", "🚀 Future Staffing Forecast"])

    with tab1:
        st.subheader(f"Historical Dynamics: {selected_site}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Team 1 Production", f"{avg_prod_vol:,.0f} Units")
        c2.metric("Historical Sampling", f"{hist_sampling_rate:.1f}%")
        c3.metric("Team 2 Verify Units", f"{avg_audit_vol:,.0f} Units")
        c4.metric("Verification AHT", f"{cleaned_aht:.1f}s")

        st.markdown("### 🔎 Locale-Specific Sampling Rates")
        breakdown = []
        for loc in site_locales:
            loc_qc = df_qc_site[df_qc_site['locale'] == loc]
            loc_aht_data = df_merc[aht_mask & (df_merc['Column-2:Locale'] == loc)]['Raw_AHT']
            
            p_units = loc_qc['production_created_units'].sum()
            a_units = loc_qc['audit_created_units'].sum()
            s_rate = (a_units / p_units * 100) if p_units > 0 else 0
            l_aht = loc_aht_data[loc_aht_data <= loc_aht_data.quantile(0.95)].mean() if not loc_aht_data.empty else 0
            
            breakdown.append({
                "Locale": loc,
                "T1 Prod (Total)": f"{p_units:,.0f}",
                "Sampling %": f"{s_rate:.1f}%",
                "T2 AHT (s)": f"{l_aht:.1f}"
            })
        st.dataframe(pd.DataFrame(breakdown), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Simulate Team 2 Needs")
        
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            forecast_weeks = st.slider("Forecast Range (Weeks)", 1, 4, 1)
            target_sampling = st.slider("Set Target Sampling %", 1.0, 50.0, float(hist_sampling_rate) if hist_sampling_rate > 0 else 5.0)
        
        # Calculations
        future_prod_vol = avg_prod_vol * (1 + (avg_growth * forecast_weeks))
        future_audit_vol = future_prod_vol * (target_sampling / 100)
        
        # FTE Calculation for Team 2
        total_verify_hours = (future_audit_vol * cleaned_aht) / 3600
        team2_needed = total_verify_hours / (prod_hours * 5) # 5-day week
        
        st.divider()
        m1, m2, m3 = st.columns(3)
        m1.metric("Exp. Production (T1)", f"{future_prod_vol:,.0f}")
        m2.metric("Exp. Verifications (T2)", f"{future_audit_vol:,.0f}")
        m3.metric("Team 2 FTE Needed", f"{team2_needed:.1f}")

        # Gap Analysis
        gap = team2_needed - team2_size
        if gap > 0:
            st.error(f"⚠️ **Headcount Deficit:** You need **{gap:.1f}** more people in Team 2 to meet the {target_sampling}% sampling target.")
        else:
            st.success(f"✅ **Headcount Surplus:** Team 2 is currently overstaffed by **{abs(gap):.1f}** people for this workflow.")

else:
    st.info("Please upload your Quality Central and Mercury CSVs to begin the simulation.")
