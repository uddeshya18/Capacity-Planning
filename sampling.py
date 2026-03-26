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

    # Calculate AHT (Fixes blank AHT issue)
    df_m['Calc_AHT'] = 3600 * (pd.to_numeric(df_m['Processed Hours'], errors='coerce') + 
                               pd.to_numeric(df_m['Manual Skip Hours'], errors='coerce')) / \
                               pd.to_numeric(df_m['Processed Units'], errors='coerce').replace(0, np.nan)
    
    # 2. DATA DEDUPLICATION (Fixes en_US High Volume Issue)
    # The QC file repeats batch units across rows. We must take the first per batch ID.
    batch_cols = ['execution_batch_id', 'workflow_name', 'locale', 'Audit Creation Period Week']
    df_q_dedup = df_q.groupby(batch_cols).agg({
        'audit_created_units': 'first',
        'production_created_units': 'first'
    }).reset_index()

    # 3. FILTERING & GROWTH
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_sites = st.sidebar.multiselect("Filter Site:", all_sites, default=all_sites)
    
    site_locales = df_m[df_m['Column-1:Site'].isin(selected_sites)]['Column-2:Locale'].unique()
    f_q = df_q_dedup[df_q_dedup['locale'].isin(site_locales)]
    f_m = df_m[df_m['Column-1:Site'].isin(selected_sites)]

    # Raw Growth Logic (Uncapped)
    site_growth_val = 0.0
    if not f_q.empty:
        weekly_sum = f_q.groupby('Audit Creation Period Week')['audit_created_units'].sum().reset_index()
        u = weekly_sum['audit_created_units'].values
        if len(u) > 1:
            diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
            site_growth_val = np.mean(diffs) if diffs else 0.0

    st.sidebar.metric(label="📈 Estimated Weekly Growth", value=f"{site_growth_val * 100:.2f}%")

    # 4. AGGREGATION (Average Week baseline)
    num_weeks = len(f_q['Audit Creation Period Week'].unique()) if not f_q.empty else 1
    
    wf_base = f_q.groupby('workflow_name').agg({
        'audit_created_units': 'sum', 
        'production_created_units': 'sum'
    }).reset_index()
    
    loc_base = f_q.groupby('locale').agg({
        'audit_created_units': 'sum', 
        'production_created_units': 'sum'
    }).reset_index()

    def get_trimmed_aht(series):
        clean = series.dropna()
        return clean[clean <= clean.quantile(0.95)].mean() if not clean.empty else 0

    # --- TABS (Mirrored Layout) ---
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 Future Forecast Explorer"])

    with tab1:
        st.subheader("Historical Weekly Average Breakdown")
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### 🛠️ Breakdown by Workflow")
            wf_list = []
            for _, row in wf_base.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
                if aht > 0:
                    wf_list.append({
                        "Workflow Name": row['workflow_name'],
                        "Avg Weekly Tasks": int(row['audit_created_units'] / num_weeks),
                        "Sampling %": f"{(row['audit_created_units']/row['production_created_units']*100):.1f}%",
                        "Cleaned AHT (s)": f"{aht:.1f}"
                    })
            st.dataframe(pd.DataFrame(wf_list), use_container_width=True, hide_index=True)

        with col2:
            st.markdown("### 📍 Breakdown by Locale")
            loc_list = []
            for _, row in loc_base.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
                if aht > 0:
                    loc_list.append({
                        "Locale": row['locale'],
                        "Avg Weekly Tasks": int(row['audit_created_units'] / num_weeks),
                        "Sampling %": f"{(row['audit_created_units']/row['production_created_units']*100):.1f}%",
                        "Cleaned AHT (s)": f"{aht:.1f}"
                    })
            st.dataframe(pd.DataFrame(loc_list), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Team 2 Verification Forecast")
        st.caption(f"📅 **Current Date:** {datetime.now().strftime('%d %b %Y')}")
        
        week_options = [f"Week {i} ({(current_monday + timedelta(weeks=i)).strftime('%d %b')} - {(current_monday + timedelta(weeks=i, days=4)).strftime('%d %b')})" for i in range(1, 5)]
        selected_week = st.selectbox("Select Prediction Week:", week_options)
        week_idx = week_options.index(selected_week) + 1

        f_col1, f_col2 = st.columns(2)

        with f_col1:
            st.markdown(f"### 🛠️ Workflow Forecast")
            wf_pred = []
            for _, row in wf_base.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
                if aht > 0:
                    pred_tasks = (row['audit_created_units'] / num_weeks) * (1 + (site_growth_val * week_idx))
                    hc = (pred_tasks * aht) / (3600 * prod_hours * 5)
                    wf_pred.append({
                        "Workflow Name": row['workflow_name'],
                        "Expected Tasks": int(pred_tasks),
                        "HC Needed": f"{hc:.2f} HC",
                        "Staffing Gap": f"{qas_per_site - hc:.2f} Gap"
                    })
            st.dataframe(pd.DataFrame(wf_pred), use_container_width=True, hide_index=True)

        with f_col2:
            st.markdown(f"### 📍 Locale Forecast")
            loc_pred = []
            for _, row in loc_base.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
                if aht > 0:
                    pred_tasks = (row['audit_created_units'] / num_weeks) * (1 + (site_growth_val * week_idx))
                    hc = (pred_tasks * aht) / (3600 * prod_hours * 5)
                    loc_pred.append({
                        "Locale": row['locale'],
                        "Expected Tasks": int(pred_tasks),
                        "HC Needed": f"{hc:.2f} HC",
                        "Staffing Gap": f"{qas_per_site - hc:.2f} Gap"
                    })
            st.dataframe(pd.DataFrame(loc_pred), use_container_width=True, hide_index=True)

else:
    st.info("Please upload your Mercury and QC files to continue.")
