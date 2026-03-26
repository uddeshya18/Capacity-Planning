import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- UI THEME (Standard Slate/White) ---
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

qas_per_site = st.sidebar.number_input("Current Team 2 Headcount", min_value=1, value=10)
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

    # Calculate Raw AHT from Mercury
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

    st.sidebar.metric(label="📈 Estimated Weekly Growth", value=f"{site_growth_val * 100:.2f}%")
    st.sidebar.divider()

    # 3. ANALYSIS LOGIC
    num_weeks = len(df_q['Audit Creation Period Week'].unique())
    f_m = df_m[df_m['Column-1:Site'].isin(selected_sites)]
    f_q = df_q[df_q['locale'].isin(site_locales)]

    def get_trimmed_aht(series):
        clean = series.dropna()
        if clean.empty: return 0.0
        return clean[clean <= clean.quantile(0.95)].mean()

    # --- TAB 1: HISTORICAL ---
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 Future Forecast Explorer"])

    with tab1:
        st.subheader("Historical Weekly Averages")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 🛠️ Breakdown by Workflow")
            wf_stats = f_q.groupby('workflow_name').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
            wf_list = []
            for _, row in wf_stats.iterrows():
                aht_val = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
                if aht_val > 0: # Filter out 0 AHT
                    wf_list.append({
                        "Workflow Name": row['workflow_name'],
                        "Avg Weekly Tasks": int(row['audit_created_units'] / num_weeks),
                        "Sampling %": f"{(row['audit_created_units']/row['production_created_units']*100):.1f}%",
                        "Cleaned AHT (s)": f"{aht_val:.1f}"
                    })
            st.dataframe(pd.DataFrame(wf_list), use_container_width=True, hide_index=True)

        with col2:
            st.markdown("### 📍 Breakdown by Locale")
            loc_stats = f_q.groupby('locale').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
            loc_list = []
            for _, row in loc_stats.iterrows():
                aht_val = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
                if aht_val > 0:
                    loc_list.append({
                        "Locale": row['locale'],
                        "Avg Weekly Tasks": int(row['audit_created_units'] / num_weeks),
                        "Sampling %": f"{(row['audit_created_units']/row['production_created_units']*100):.1f}%",
                        "Cleaned AHT (s)": f"{aht_val:.1f}"
                    })
            st.dataframe(pd.DataFrame(loc_list), use_container_width=True, hide_index=True)

    # --- TAB 2: FORECAST ---
    with tab2:
        st.subheader("Team 2 Verification Forecast")
        st.caption(f"📅 **Current Date:** {datetime.now().strftime('%d %b %Y')}")
        
        # WEEK SELECTOR
        week_options = []
        for i in range(1, 5):
            start = current_monday + timedelta(weeks=i)
            end = start + timedelta(days=4)
            week_options.append(f"Week {i} ({start.strftime('%d %b')} - {end.strftime('%d %b')})")
        
        selected_week = st.selectbox("Select Prediction Week:", week_options)
        week_idx = week_options.index(selected_week) + 1

        f_col1, f_col2 = st.columns(2)

        with f_col1:
            st.markdown(f"### 🛠️ Workflow Forecast ({selected_week.split(' ')[0]})")
            wf_forecast = []
            for _, row in wf_stats.iterrows():
                aht_val = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
                if aht_val > 0:
                    base_tasks = row['audit_created_units'] / num_weeks
                    pred_tasks = base_tasks * (1 + (site_growth_val * week_idx))
                    hc_req = (pred_tasks * aht_val) / (3600 * prod_hours * 5)
                    wf_forecast.append({
                        "Workflow Name": row['workflow_name'],
                        "Expected Tasks": int(pred_tasks),
                        "HC Needed": f"{hc_req:.2f}"
                    })
            st.dataframe(pd.DataFrame(wf_forecast), use_container_width=True, hide_index=True)

        with f_col2:
            st.markdown(f"### 📍 Locale Forecast ({selected_week.split(' ')[0]})")
            loc_forecast = []
            for _, row in loc_stats.iterrows():
                aht_val = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
                if aht_val > 0:
                    base_tasks = row['audit_created_units'] / num_weeks
                    pred_tasks = base_tasks * (1 + (site_growth_val * week_idx))
                    hc_req = (pred_tasks * aht_val) / (3600 * prod_hours * 5)
                    loc_forecast.append({
                        "Locale": row['locale'],
                        "Expected Tasks": int(pred_tasks),
                        "HC Needed": f"{hc_req:.2f}"
                    })
            st.dataframe(pd.DataFrame(loc_forecast), use_container_width=True, hide_index=True)

        st.info(f"💡 Forecast assumes a raw weekly volume growth of **{site_growth_val*100:.2f}%**.")

else:
    st.info("Please upload your Mercury and Quality Central files to begin.")
