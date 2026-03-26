import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

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

st.title("📊 Strategic Capacity Planner")

# --- SIDEBAR ---
st.sidebar.header("⚙️ Global Settings")
merc_file = st.sidebar.file_uploader("Upload Mercury Metrics (AHT)", type="csv")
qc_file = st.sidebar.file_uploader("Upload Quality Central (Volume)", type="csv")

qas_per_site = st.sidebar.number_input("Current QAs per Locale", min_value=1, value=10)
prod_hours = st.sidebar.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

def get_monday(d):
    return d - timedelta(days=d.weekday())

current_monday = get_monday(datetime.now())

if merc_file and qc_file:
    # 1. LOAD & NORMALIZE
    df_m = pd.read_csv(merc_file)
    df_q = pd.read_csv(qc_file)

    for d in [df_m, df_q]:
        for col in d.columns:
            if d[col].dtype == 'object':
                d[col] = d[col].astype(str).str.strip()

    # Calculate Manual AHT from Mercury
    df_m['Raw_AHT'] = 3600 * (df_m['Processed Hours'] + df_m['Manual Skip Hours']) / df_m['Processed Units'].replace(0, np.nan)
    
    # 2. GROWTH & FILTERS
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_sites = st.sidebar.multiselect("Filter Site:", all_sites, default=all_sites)
    
    # Map Locales to Selected Sites
    site_locales = df_m[df_m['Column-1:Site'].isin(selected_sites)]['Column-2:Locale'].unique()
    df_q_filtered = df_q[df_q['locale'].isin(site_locales)]
    
    # UNCAPPED GROWTH CALCULATION
    site_growth_val = 0.0
    if not df_q_filtered.empty:
        site_weekly = df_q_filtered.groupby('Audit Creation Period Week')['audit_created_units'].sum().reset_index()
        u = site_weekly['audit_created_units'].values
        if len(u) > 1:
            diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
            site_growth_val = np.mean(diffs) if diffs else 0.0

    st.sidebar.metric(label="📈 Estimated Raw Growth", value=f"{site_growth_val * 100:.2f}%")
    
    # 3. ANALYSIS TABS
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 4-Week Prediction Forecast"])

    num_weeks = len(df_q['Audit Creation Period Week'].unique())

    with tab1:
        st.subheader("Historical Average Weekly Performance")
        
        hist_results = []
        for loc in sorted(site_locales):
            m_loc = df_m[(df_m['Column-2:Locale'] == loc) & (df_m['Column-1:Site'].isin(selected_sites))]
            q_loc = df_q[df_q['locale'] == loc]
            
            if q_loc.empty: continue
            
            # Correct Sampling % Calculation
            total_prod = q_loc['production_created_units'].sum()
            total_audit = q_loc['audit_created_units'].sum()
            sampling_pct = (total_audit / total_prod * 100) if total_prod > 0 else 0
            
            # Trimmed AHT
            aht_series = m_loc['Raw_AHT'].dropna()
            cleaned_aht = aht_series[aht_series <= aht_series.quantile(0.95)].mean() if not aht_series.empty else 0
            
            hist_results.append({
                "Locale": loc,
                "Avg Weekly Audit Vol": int(total_audit / num_weeks),
                "Avg Weekly Prod Vol": int(total_prod / num_weeks),
                "Sampling %": f"{sampling_pct:.2f}%",
                "Cleaned AHT (s)": f"{cleaned_aht:.1f}"
            })
        
        st.dataframe(pd.DataFrame(hist_results), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Next 4 Weeks Capacity Prediction")
        
        # Build Week Range Headers (Mon-Fri)
        forecast_headers = []
        for i in range(1, 5):
            start = current_monday + timedelta(weeks=i)
            end = start + timedelta(days=4)
            forecast_headers.append(f"Wk {i} ({start.strftime('%d %b')} - {end.strftime('%d %b')})")

        forecast_table = []
        for loc in sorted(site_locales):
            m_loc = df_m[(df_m['Column-2:Locale'] == loc) & (df_m['Column-1:Site'].isin(selected_sites))]
            q_loc = df_q[df_q['locale'] == loc]
            
            if q_loc.empty: continue
            
            base_audit_vol = q_loc['audit_created_units'].sum() / num_weeks
            aht_series = m_loc['Raw_AHT'].dropna()
            cleaned_aht = aht_series[aht_series <= aht_series.quantile(0.95)].mean() if not aht_series.empty else 0
            
            row = {"Locale": loc}
            for i in range(1, 5):
                # Apply Uncapped Growth per Week
                pred_vol = base_audit_vol * (1 + (site_growth_val * i))
                req_hours = (pred_vol * cleaned_aht) / 3600
                hc_needed = req_hours / (prod_hours * 5)
                
                row[forecast_headers[i-1]] = f"{hc_needed:.2f} HC"
            
            forecast_table.append(row)

        st.dataframe(pd.DataFrame(forecast_table), use_container_width=True, hide_index=True)
        st.info(f"💡 Predictions are based on a baseline growth rate of **{site_growth_val*100:.2f}%** per week.")

else:
    st.info("Please upload both CSV files to generate the planner.")
