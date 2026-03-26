import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- UI THEME (Unified Slate/White) ---
st.markdown("""
    <style>
    /* Unified Background for Sidebar and Main Page */
    .stApp, [data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child {
        background-color: #f8fafc !important;
    }
    
    /* Metrics Styling */
    div[data-testid="metric-container"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }

    /* Tab and Dataframe Styling */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #f1f5f9;
        border-radius: 8px 8px 0 0;
        padding: 10px 20px;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📊 Strategic Capacity Planner")

# --- SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Data Source")
    qc_file = st.file_uploader("Upload Volume (Quality Central)", type="csv")
    merc_file = st.file_uploader("Upload AHT (Mercury Metrics)", type="csv")
    
    st.divider()
    qas_input = st.number_input("Current QAs per Site", min_value=0, value=10)
    prod_hours = st.slider("Daily Productive Hours", 4.0, 9.0, 7.5)

# Date Utility
current_monday = (datetime.now() - timedelta(days=datetime.now().weekday()))

if qc_file and merc_file:
    # 1. LOAD & NORMALIZE DATA
    df_qc = pd.read_csv(qc_file)
    df_merc = pd.read_csv(merc_file)

    # Clean string columns to prevent matching errors
    df_qc['workflow_name'] = df_qc['workflow_name'].astype(str).str.strip()
    df_merc['Column-4:Transformation Type'] = df_merc['Column-4:Transformation Type'].astype(str).str.strip()
    df_merc['Column-1:Site'] = df_merc['Column-1:Site'].astype(str).str.strip()
    df_merc['Column-2:Locale'] = df_merc['Column-2:Locale'].astype(str).str.strip()

    # 2. CALCULATE CLEANED AHT (Mercury)
    # Formula: 3600 * (Hours + Skip Hours) / Units
    df_merc['Raw_AHT'] = 3600 * (df_merc['Processed Hours'] + df_merc['Manual Skip Hours']) / df_merc['Processed Units'].replace(0, np.nan)
    df_merc = df_merc.dropna(subset=['Raw_AHT'])
    df_merc = df_merc[~df_merc['Raw_AHT'].isin([np.inf, -np.inf])]

    # 3. DYNAMIC FILTERS (Auto-Locale Logic)
    sites = sorted(df_merc['Column-1:Site'].unique())
    selected_site = st.sidebar.selectbox("Select Site:", sites)
    
    # Auto-select all locales for the site
    site_locales = sorted(df_merc[df_merc['Column-1:Site'] == selected_site]['Column-2:Locale'].unique())
    selected_locales = st.sidebar.multiselect("Locales:", site_locales, default=site_locales)
    
    # Workflow Filter (Only showing workflows that exist in BOTH files)
    common_wfs = sorted(list(set(df_qc['workflow_name']) & set(df_merc['Column-4:Transformation Type'])))
    wf_choice = st.sidebar.selectbox("Select Workflow:", common_wfs)

    # 4. VOLUME & GROWTH (Quality Central - Sampling Units)
    wf_vol_df = df_qc[df_qc['workflow_name'] == wf_choice]
    weekly_data = wf_vol_df.groupby('Audit Creation Period Week')['audit_created_units'].sum().reset_index()
    
    if not weekly_data.empty:
        baseline_vol = weekly_data['audit_created_units'].mean()
        # Direct Average Growth (Uncapped)
        weekly_data['growth'] = weekly_data['audit_created_units'].pct_change()
        avg_growth = weekly_data['growth'].mean() if len(weekly_data) > 1 else 0.0
    else:
        baseline_vol, avg_growth = 0, 0

    st.sidebar.metric("Workflow Growth", f"{avg_growth:.1%}")

    # 5. ANALYSIS TABS
    tab1, tab2 = st.tabs(["📋 Historical Audit", "📈 Predictive Planning"])

    # Helper: Trimmed Mean (95th Percentile)
    def calculate_cleaned_aht(data):
        if data.empty: return 0.0
        q_95 = data.quantile(0.95)
        return data[data <= q_95].mean()

    with tab1:
        st.subheader(f"Historical Audit: {wf_choice}")
        
        # Site/Locale AHT Mask
        aht_mask = (df_merc['Column-1:Site'] == selected_site) & \
                   (df_merc['Column-2:Locale'].isin(selected_locales)) & \
                   (df_merc['Column-4:Transformation Type'] == wf_choice)
        
        target_aht_series = df_merc[aht_mask]['Raw_AHT']
        overall_cleaned_aht = calculate_cleaned_aht(target_aht_series)

        m1, m2, m3 = st.columns(3)
        m1.metric("Cleaned AHT (s)", f"{overall_cleaned_aht:.1f}s")
        m2.metric("Baseline Volume", f"{baseline_vol:,.0f}")
        m3.metric("Growth Rate", f"{avg_growth:.1%}")

        st.markdown("### 🗺️ Locale Performance Breakdown")
        breakdown = []
        for loc in selected_locales:
            loc_data = df_merc[aht_mask & (df_merc['Column-2:Locale'] == loc)]['Raw_AHT']
            loc_aht = calculate_cleaned_aht(loc_data)
            breakdown.append({
                "Site": selected_site,
                "Locale": loc,
                "Cleaned AHT (s)": f"{loc_aht:.1f}",
                "Status": "Data Found" if loc_aht > 0 else "No Data"
            })
        st.dataframe(pd.DataFrame(breakdown), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Capacity Forecast")
        
        horizon = st.selectbox("Select Prediction Week:", ["Week 1", "Week 2", "Week 3", "Week 4"])
        week_num = int(horizon.split()[-1])
        
        # Predictions
        expected_vol = baseline_vol * (1 + (avg_growth * week_num))
        total_seconds = expected_vol * overall_cleaned_aht
        hc_req = (total_seconds / 3600) / (prod_hours * 5) # 5 day work week
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Expected Volume", f"{expected_vol:,.0f}")
        c2.metric("Headcount Required", f"{hc_req:.2f}")
        c3.metric("Staffing Gap", f"{hc_req - qas_input:.2f}")

        st.info(f"This forecast is based on the **Sampling Volume** found in Quality Central for the **{wf_choice}** workflow.")

else:
    st.info("Please upload both Quality Central (Volume) and Mercury (AHT) CSV files to begin.")
