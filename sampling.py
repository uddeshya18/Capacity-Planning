import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- UI THEME (Standardized as per your request) ---
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

# --- SIDEBAR: GLOBAL CONTROLS ---
st.sidebar.header("⚙️ Global Settings")
merc_file = st.sidebar.file_uploader("Upload Mercury Metrics (AHT)", type="csv")
qc_file = st.sidebar.file_uploader("Upload Quality Central (Volume)", type="csv")

qas_per_site = st.sidebar.number_input("Current QAs (Actual)", min_value=1, value=10)
prod_hours = st.sidebar.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

def get_monday(d):
    return d - timedelta(days=d.weekday())

current_monday = get_monday(datetime.now())

if merc_file and qc_file:
    # 1. LOAD & CLEAN DATA
    df_m = pd.read_csv(merc_file)
    df_q = pd.read_csv(qc_file)

    # Normalize Strings to prevent invisible matching errors
    for d in [df_m, df_q]:
        for col in d.columns:
            if d[col].dtype == 'object':
                d[col] = d[col].astype(str).str.strip()

    # Calculate AHT (Fixes blank AHT issue)
    df_m['Calc_AHT'] = 3600 * (pd.to_numeric(df_m['Processed Hours'], errors='coerce') + 
                               pd.to_numeric(df_m['Manual Skip Hours'], errors='coerce')) / \
                               pd.to_numeric(df_m['Processed Units'], errors='coerce').replace(0, np.nan)
    
    # 2. FILTERING & GROWTH (UNCAPPED)
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_sites = st.sidebar.multiselect("Filter Site:", all_sites, default=all_sites)
    
    site_locales = df_m[df_m['Column-1:Site'].isin(selected_sites)]['Column-2:Locale'].unique()
    df_q_site = df_q[df_q['locale'].isin(site_locales)]

    # Raw Growth Logic (Uncapped)
    site_growth_val = 0.0
    if not df_q_site.empty:
        site_weekly = df_q_site.groupby('Audit Creation Period Week')['audit_created_units'].sum().reset_index()
        u = site_weekly['audit_created_units'].values
        if len(u) > 1:
            diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
            site_growth_val = np.mean(diffs) if diffs else 0.0

    st.sidebar.metric(label="📈 Estimated Growth", value=f"{site_growth_val * 100:.2f}%")
    st.sidebar.divider()

    # 3. TABS
    tab1, tab2 = st.tabs(["📊 Historical Audit Performance", "🚀 Future Forecast Explorer"])

    num_weeks_in_data = len(df_q['Audit Creation Period Week'].unique())

    with tab1:
        st.subheader("Historical Weekly Average (Team 2)")
        
        hist_results = []
        # Filter both for selected site locales
        f_m = df_m[df_m['Column-1:Site'].isin(selected_sites)]
        f_q = df_q[df_q['locale'].isin(site_locales)]
        
        # Group by Workflow & Locale to ensure workflow visibility
        stats = f_q.groupby(['workflow_name', 'locale']).agg({
            'audit_created_units': 'sum',
            'production_created_units': 'sum'
        }).reset_index()

        for _, row in stats.iterrows():
            wf = row['workflow_name']
            loc = row['locale']
            
            # Find matching AHT from Mercury
            aht_subset = f_m[(f_m['Column-4:Transformation Type'] == wf) & (f_m['Column-2:Locale'] == loc)]['Calc_AHT'].dropna()
            cleaned_aht = aht_subset[aht_subset <= aht_subset.quantile(0.95)].mean() if not aht_subset.empty else 0
            
            # Sampling % calculation
            s_rate = (row['audit_created_units'] / row['production_created_units'] * 100) if row['production_created_units'] > 0 else 0
            
            hist_results.append({
                "Workflow Name": wf,
                "Locale": loc,
                "Avg Weekly Tasks": int(row['audit_created_units'] / num_weeks_in_data),
                "Sampling %": f"{s_rate:.2f}%",
                "Cleaned AHT (s)": f"{cleaned_aht:.1f}"
            })
        
        st.dataframe(pd.DataFrame(hist_results), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Team 2 Forecast Tracker")
        st.caption(f"📅 Current Date: {datetime.now().strftime('%d %b %Y')}")
        
        # WEEK SELECTOR DROP DOWN
        week_options = []
        for i in range(1, 5):
            start = current_monday + timedelta(weeks=i)
            end = start + timedelta(days=4)
            week_options.append(f"Week {i} ({start.strftime('%d %b')} - {end.strftime('%d %b')})")
        
        selected_week_label = st.selectbox("Select Prediction Week:", week_options)
        week_idx = week_options.index(selected_week_label) + 1
        
        forecast_results = []
        for _, row in stats.iterrows():
            wf = row['workflow_name']
            loc = row['locale']
            
            aht_subset = f_m[(f_m['Column-4:Transformation Type'] == wf) & (f_m['Column-2:Locale'] == loc)]['Calc_AHT'].dropna()
            cleaned_aht = aht_subset[aht_subset <= aht_subset.quantile(0.95)].mean() if not aht_subset.empty else 0
            
            # Baseline weekly audits
            base_tasks = row['audit_created_units'] / num_weeks_in_data
            # Future Forecast (Uncapped Growth)
            pred_tasks = base_tasks * (1 + (site_growth_val * week_idx))
            
            req_hours = (pred_tasks * cleaned_aht) / 3600
            hc_needed = req_hours / (prod_hours * 5)
            
            forecast_results.append({
                "Workflow Name": wf,
                "Locale": loc,
                "Expected Tasks": int(pred_tasks),
                "Target Week": selected_week_label.split('(')[1].replace(')', ''),
                "HC Needed": f"{hc_needed:.2f}",
                "Surplus/Deficit": f"{qas_per_site - hc_needed:.2f}"
            })

        st.dataframe(pd.DataFrame(forecast_results), use_container_width=True, hide_index=True)
        st.info(f"💡 Forecast is applying a raw weekly growth of **{site_growth_val*100:.2f}%** based on historical trends.")

else:
    st.info("Please upload your Mercury and Quality Central files to begin.")
