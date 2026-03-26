import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- UNIFIED UI COLOR THEME ---
st.markdown("""
    <style>
    .stApp, [data-testid="stSidebar"] { background-color: #f8fafc; }
    div[data-testid="metric-container"] {
        background-color: #ffffff; border: 1px solid #e2e8f0;
        padding: 15px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .stDataFrame { border-radius: 12px; }
    </style>
    """, unsafe_allow_html=True)

st.title("📊 Strategic Capacity Planner")

# --- SIDEBAR: GLOBAL CONTROLS ---
with st.sidebar:
    st.header("⚙️ Data Inputs")
    qc_file = st.file_uploader("Upload Volume (Quality Central)", type="csv")
    mercury_file = st.file_uploader("Upload AHT (Mercury Metrics)", type="csv")
    
    st.divider()
    qas_per_site = st.number_input("Current QAs (Target)", min_value=1, value=10)
    prod_hours = st.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

# Date Utility
current_monday = (datetime.now() - timedelta(days=datetime.now().weekday()))

if qc_file and mercury_file:
    # 1. LOAD & CLEAN DATA
    df_qc = pd.read_csv(qc_file)
    df_merc = pd.read_csv(mercury_file)

    # Clean AHT Calculation: Handle 0 division and Inf
    # Formula: 3600 * (Processed Hours + Manual Skip Hours) / Processed Units
    df_merc['Raw_AHT'] = 3600 * (df_merc['Processed Hours'] + df_merc['Manual Skip Hours']) / df_merc['Processed Units'].replace(0, np.nan)
    df_merc = df_merc.dropna(subset=['Raw_AHT'])
    df_merc = df_merc[~df_merc['Raw_AHT'].isin([np.inf, -np.inf])]

    # 2. DYNAMIC FILTERS
    all_sites = sorted(df_merc['Column-1:Site'].dropna().unique())
    selected_site = st.sidebar.selectbox("Select Site:", all_sites)
    
    # Auto-select all locales for the chosen site
    site_locales = sorted(df_merc[df_merc['Column-1:Site'] == selected_site]['Column-2:Locale'].unique())
    selected_locales = st.sidebar.multiselect("Locales (Auto-Selected):", site_locales, default=site_locales)
    
    # Workflow Filter (Pulling from Mercury to ensure AHT matches)
    workflow_list = sorted(df_merc['Column-4:Transformation Type'].dropna().unique())
    wf_choice = st.sidebar.selectbox("Select Transformation Workflow:", workflow_list)

    # 3. CALCULATE VOLUME & GROWTH (QUALITY CENTRAL)
    # Filter QC data for the selected workflow
    df_qc_filtered = df_qc[df_qc['workflow_name'] == wf_choice]
    
    if not df_qc_filtered.empty:
        weekly_vol = df_qc_filtered.groupby('Audit Creation Period Week')['audit_created_units'].sum().reset_index()
        baseline_vol = weekly_vol['audit_created_units'].mean()
        
        # Direct Growth (No Cap)
        weekly_vol['growth'] = weekly_vol['audit_created_units'].pct_change()
        avg_growth_val = weekly_vol['growth'].mean() if len(weekly_vol) > 1 else 0.0
    else:
        baseline_vol, avg_growth_val = 0, 0

    st.sidebar.metric(label="📈 Avg Weekly Growth", value=f"{avg_growth_val:.2%}")

    # 4. TABS
    tab1, tab2 = st.tabs(["📊 Historical Audit", "🚀 Future Prediction"])

    def get_trimmed_mean(series):
        if series.empty: return 0
        limit = series.quantile(0.95)
        return series[series <= limit].mean()

    with tab1:
        st.subheader(f"Historical Audit: {wf_choice}")
        
        # Site-wide AHT for the selected workflow
        mask = (df_merc['Column-1:Site'] == selected_site) & (df_merc['Column-4:Transformation Type'] == wf_choice)
        site_aht_data = df_merc[mask]['Raw_AHT']
        cleaned_aht_val = get_trimmed_mean(site_aht_data)

        c1, c2, c3 = st.columns(3)
        c1.metric("Cleaned AHT (s)", f"{cleaned_aht_val:.1f}")
        c2.metric("Historical Avg Units", f"{baseline_vol:,.0f}")
        c3.metric("Growth Rate", f"{avg_growth_val:.1%}")

        st.markdown("### 🛠️ Locale Breakdown (Historical Data)")
        loc_stats = []
        for loc in selected_locales:
            loc_mask = mask & (df_merc['Column-2:Locale'] == loc)
            loc_aht = get_trimmed_mean(df_merc[loc_mask]['Raw_AHT'])
            # Match QC locale name to Mercury locale if needed, otherwise use mercury
            loc_stats.append({
                "Site": selected_site,
                "Locale": loc,
                "Cleaned AHT (s)": f"{loc_aht:.1f}",
                "Workflows Tracked": len(df_merc[loc_mask])
            })
        st.dataframe(pd.DataFrame(loc_stats), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Predictive Capacity Roadmap")
        
        week_options = [f"Week {i+1}" for i in range(4)]
        selected_week = st.selectbox("Select Forecast Horizon:", week_options)
        week_idx = int(selected_week.split()[-1])
        
        # Capacity Math
        pred_vol = baseline_vol * (1 + (avg_growth_val * week_idx))
        req_hours = (pred_vol * cleaned_aht_val) / 3600
        hc_needed = req_hours / (prod_hours * 5) # Based on 5-day week
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Forecasted Volume", f"{pred_vol:,.0f}")
        col2.metric("Target Headcount", f"{hc_needed:.1f}")
        col3.metric("Utilization Gap", f"{(hc_needed/qas_per_site)*100:.1f}%" if qas_per_site > 0 else "0%")

        st.write("---")
        st.info(f"The **{avg_growth_val:.1%}** growth is derived from the **Quality Central** volume history, while performance is benchmarked from **Mercury Metrics**.")

else:
    st.info("Please upload both Quality Central (Volume) and Mercury Metrics (AHT) CSV files to launch.")
