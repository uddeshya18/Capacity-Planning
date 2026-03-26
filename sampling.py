import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- UNIFIED UI COLOR THEME (CSS) ---
st.markdown("""
    <style>
    /* Main Background & Sidebar Match */
    .stApp, [data-testid="stSidebar"] {
        background-color: #f8fafc;
    }
    
    /* Metric Card Styling */
    div[data-testid="metric-container"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 15px;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }

    /* Tab Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #f1f5f9;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("📊 Strategic Capacity Planner")

# --- SIDEBAR: GLOBAL CONTROLS ---
with st.sidebar:
    st.header("⚙️ Data Inputs")
    qc_file = st.file_uploader("Upload Volume (Quality Central)", type="csv")
    mercury_file = st.file_uploader("Upload AHT (Mercury Metrics)", type="csv")
    
    st.divider()
    
    qas_per_site = st.number_input("Current QAs per Locale", min_value=1, value=10)
    prod_hours = st.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

# Date Utility
def get_monday(d):
    return d - timedelta(days=d.weekday())
current_monday = get_monday(datetime.now())

if qc_file and mercury_file:
    # 1. LOAD DATA
    df_qc = pd.read_csv(qc_file)
    df_merc = pd.read_csv(mercury_file)

    # 2. PERFORMANCE CALCULATION (MERCURY)
    # Formula: 3600 * (Processed Hours + Manual Skip Hours) / Processed Units
    df_merc['Raw_AHT'] = 3600 * (df_merc['Processed Hours'] + df_merc['Manual Skip Hours']) / df_merc['Processed Units']
    
    # 3. DYNAMIC FILTERING (Auto-Locale Selection)
    all_sites = sorted(df_merc['Column-1:Site'].dropna().unique())
    selected_site = st.sidebar.selectbox("Select Site:", all_sites)
    
    # Auto-select all locales belonging to the selected site
    site_locales = sorted(df_merc[df_merc['Column-1:Site'] == selected_site]['Column-2:Locale'].unique())
    selected_locales = st.sidebar.multiselect("Locales (Auto-Selected):", site_locales, default=site_locales)
    
    # Workflow Filter (from QC File)
    all_workflows = sorted(df_qc['workflow_name'].dropna().unique())
    wf_choice = st.sidebar.selectbox("Select Workflow:", all_workflows)

    # 4. GROWTH LOGIC (Direct Volume from QC)
    df_qc_filtered = df_qc[df_qc['workflow_name'] == wf_choice]
    weekly_vol = df_qc_filtered.groupby('Audit Creation Period Week')['audit_created_units'].sum().reset_index()
    
    if not weekly_vol.empty:
        baseline_vol = weekly_vol['audit_created_units'].mean()
        weekly_vol['growth'] = weekly_vol['audit_created_units'].pct_change()
        # Direct average (no cap/floor as requested)
        avg_growth_val = weekly_vol['growth'].mean() if len(weekly_vol) > 1 else 0.0
    else:
        baseline_vol, avg_growth_val = 0, 0

    st.sidebar.metric(label="📈 Estimated Growth", value=f"{avg_growth_val:.2%}")

    # 5. TABS
    tab1, tab2 = st.tabs(["📊 Historical Audit", "🚀 Future Prediction"])

    def get_trimmed_mean(data):
        clean = data.replace([np.inf, -np.inf], np.nan).dropna()
        if len(clean) < 3: return clean.mean()
        return clean[clean <= clean.quantile(0.95)].mean()

    with tab1:
        st.subheader(f"Historical Verification: {selected_site}")
        
        # Calculate AHT for selection
        mask = (df_merc['Column-1:Site'] == selected_site) & (df_merc['Column-4:Transformation Type'] == wf_choice)
        site_aht_data = df_merc[mask]['Raw_AHT']
        cleaned_aht_val = get_trimmed_mean(site_aht_data)

        c1, c2, c3 = st.columns(3)
        c1.metric("Cleaned AHT", f"{cleaned_aht_val:.1f}s")
        c2.metric("Weekly Baseline", f"{baseline_vol:,.0f}")
        c3.metric("Growth Trend", f"{avg_growth_val:.1%}")

        st.markdown("### 🛠️ Locale Performance Breakdown")
        loc_stats = []
        for loc in selected_locales:
            loc_mask = (df_merc['Column-1:Site'] == selected_site) & (df_merc['Column-2:Locale'] == loc) & (df_merc['Column-4:Transformation Type'] == wf_choice)
            loc_aht = get_trimmed_mean(df_merc[loc_mask]['Raw_AHT'])
            loc_stats.append({"Locale": loc, "Cleaned AHT (s)": f"{loc_aht:.1f}"})
        st.dataframe(pd.DataFrame(loc_stats), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Future Forecast Explorer")
        
        week_options = [f"Week {i+1}" for i in range(4)]
        selected_week = st.selectbox("Select Forecast Week:", week_options)
        week_idx = int(selected_week.split()[-1])
        
        # Forecast Math
        pred_vol = baseline_vol * (1 + (avg_growth_val * week_idx))
        req_hours = (pred_vol * cleaned_aht_val) / 3600
        hc_needed = req_hours / (prod_hours * 5)
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Exp. Volume", f"{pred_vol:,.0f}")
        col2.metric("HC Needed", f"{hc_needed:.1f}")
        col3.metric("Utilization", f"{(hc_needed/qas_per_site)*100:.1f}%" if qas_per_site > 0 else "0%")

        st.info(f"💡 This forecast uses the direct volume trend from Quality Central to account for sampling fluctuations in {wf_choice}.")

else:
    st.info("Please upload both Quality Central (Volume) and Mercury (AHT) CSV files in the sidebar.")
