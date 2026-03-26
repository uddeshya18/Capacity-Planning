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
    qas_input = st.number_input("Current QAs (Actual)", min_value=0, value=10)
    prod_hours = st.slider("Daily Productive Hours", 4.0, 9.0, 7.5)

if qc_file and merc_file:
    # 1. LOAD & NORMALIZE DATA
    df_qc = pd.read_csv(qc_file)
    df_merc = pd.read_csv(merc_file)

    # Data Normalization (Strip spaces, handle case)
    for df, col in [(df_qc, 'workflow_name'), (df_merc, 'Column-4:Transformation Type'), 
                    (df_merc, 'Column-1:Site'), (df_merc, 'Column-2:Locale')]:
        df[col] = df[col].astype(str).str.strip()

    # 2. CALCULATE AHT & SAMPLING (The "Source of Truth")
    # AHT Formula: 3600 * (Hours + Skip Hours) / Units
    df_merc['Raw_AHT'] = 3600 * (df_merc['Processed Hours'] + df_merc['Manual Skip Hours']) / df_merc['Processed Units'].replace(0, np.nan)
    
    # Sampling % Formula: (Audit Units / Production Units)
    df_qc['Sampling_Pct'] = (df_qc['audit_created_units'] / df_qc['production_created_units'].replace(0, np.nan)) * 100

    # 3. FILTERS
    sites = sorted(df_merc['Column-1:Site'].unique())
    selected_site = st.sidebar.selectbox("Select Site:", sites)
    
    site_locales = sorted(df_merc[df_merc['Column-1:Site'] == selected_site]['Column-2:Locale'].unique())
    selected_locales = st.sidebar.multiselect("Locales (Auto-Selected):", site_locales, default=site_locales)
    
    common_wfs = sorted(list(set(df_qc['workflow_name']) & set(df_merc['Column-4:Transformation Type'])))
    wf_choice = st.sidebar.selectbox("Select Workflow:", common_wfs)

    # 4. VOLUME & GROWTH STABILIZATION
    wf_vol_df = df_qc[df_qc['workflow_name'] == wf_choice]
    weekly_data = wf_vol_df.groupby('Audit Creation Period Week').agg({
        'audit_created_units': 'sum',
        'production_created_units': 'sum'
    }).reset_index()
    
    if not weekly_data.empty:
        baseline_vol = weekly_data['audit_created_units'].mean()
        avg_sampling = (weekly_data['audit_created_units'].sum() / weekly_data['production_created_units'].sum()) * 100
        
        # Stability Logic: 0-20% Cap/Floor to fix the 71.8% issue
        weekly_data['raw_growth'] = weekly_data['audit_created_units'].pct_change()
        weekly_data['stable_growth'] = weekly_data['raw_growth'].clip(lower=0, upper=0.20)
        avg_growth = weekly_data['stable_growth'].mean() if len(weekly_data) > 1 else 0.0
    else:
        baseline_vol, avg_growth, avg_sampling = 0, 0, 0

    st.sidebar.metric("Stabilized Growth", f"{avg_growth:.1%}")

    # 5. ANALYSIS TABS
    tab1, tab2 = st.tabs(["📋 Historical Audit", "📈 Predictive Planning"])

    def get_cleaned_aht(series):
        valid = series.dropna()
        if valid.empty: return 0.0
        # 95th Percentile Trimmed Mean
        return valid[valid <= valid.quantile(0.95)].mean()

    with tab1:
        st.subheader(f"Performance Summary: {wf_choice}")
        
        # Site/Locale Mask
        aht_mask = (df_merc['Column-1:Site'] == selected_site) & \
                   (df_merc['Column-2:Locale'].isin(selected_locales)) & \
                   (df_merc['Column-4:Transformation Type'] == wf_choice)
        
        relevant_aht = df_merc[aht_mask]['Raw_AHT']
        overall_aht = get_cleaned_aht(relevant_aht)

        m1, m2, m3 = st.columns(3)
        m1.metric("Cleaned AHT", f"{overall_aht:.1f}s")
        m2.metric("Avg Sampling Rate", f"{avg_sampling:.1f}%")
        m3.metric("Avg Weekly Vol", f"{baseline_vol:,.0f}")

        st.markdown("### 🛠️ Workflow & Locale Deep-Dive")
        breakdown = []
        for loc in selected_locales:
            loc_aht = get_cleaned_aht(df_merc[aht_mask & (df_merc['Column-2:Locale'] == loc)]['Raw_AHT'])
            loc_qc = df_qc[(df_qc['workflow_name'] == wf_choice) & (df_qc['locale'] == loc)]
            loc_sampling = (loc_qc['audit_created_units'].sum() / loc_qc['production_created_units'].sum() * 100) if not loc_qc.empty else 0
            
            breakdown.append({
                "Workflow": wf_choice,
                "Locale": loc,
                "Cleaned AHT (s)": f"{loc_aht:.1f}",
                "Sampling Rate": f"{loc_sampling:.1f}%",
                "Historical Units": int(loc_qc['audit_created_units'].sum()) if not loc_qc.empty else 0
            })
        st.dataframe(pd.DataFrame(breakdown), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Capacity Forecast Explorer")
        
        horizon = st.selectbox("Forecast Week:", ["Week 1", "Week 2", "Week 3", "Week 4"])
        week_num = int(horizon.split()[-1])
        
        # Predictions
        expected_vol = baseline_vol * (1 + (avg_growth * week_num))
        hc_req = ((expected_vol * overall_aht) / 3600) / (prod_hours * 5)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Predicted Audit Volume", f"{expected_vol:,.0f}")
        c2.metric("Target FTE", f"{hc_req:.2f}")
        c3.metric("Utilization Gap", f"{hc_req - qas_input:.2f}")

        st.info(f"💡 This plan accounts for a **{avg_sampling:.1f}%** sampling strategy for **{wf_choice}**.")

else:
    st.info("Please upload your CSV files to launch the Strategic Planner.")
