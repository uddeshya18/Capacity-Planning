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

    # Manual AHT Calculation
    df_m['Calc_AHT'] = 3600 * (pd.to_numeric(df_m['Processed Hours'], errors='coerce') + 
                               pd.to_numeric(df_m['Manual Skip Hours'], errors='coerce')) / \
                               pd.to_numeric(df_m['Processed Units'], errors='coerce').replace(0, np.nan)
    
    # 2. SITE FILTERING
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_sites = st.sidebar.multiselect("Filter Site:", all_sites, default=all_sites)
    
    site_locales = df_m[df_m['Column-1:Site'].isin(selected_sites)]['Column-2:Locale'].unique()
    f_q = df_q[df_q['locale'].isin(site_locales)]
    f_m = df_m[df_m['Column-1:Site'].isin(selected_sites)]

    # 3. GROWTH CALCULATION (Uncapped)
    site_growth_val = 0.0
    if not f_q.empty:
        # Sum by week first to find week-over-week trend
        weekly_sum = f_q.groupby('Audit Creation Period Week')['audit_created_units'].sum().reset_index()
        u = weekly_sum['audit_created_units'].values
        if len(u) > 1:
            diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
            site_growth_val = np.mean(diffs) if diffs else 0.0

    st.sidebar.metric(label="📈 Estimated Weekly Growth", value=f"{site_growth_val * 100:.2f}%")

    # 4. DATA AGGREGATION (Fixed en_US Over-counting)
    # We aggregate by Week first, then take the mean to get a true "Average Week"
    wf_base = f_q.groupby(['workflow_name', 'Audit Creation Period Week']).agg({
        'audit_created_units': 'sum', 'production_created_units': 'sum'
    }).groupby('workflow_name').mean().reset_index()

    loc_base = f_q.groupby(['locale', 'Audit Creation Period Week']).agg({
        'audit_created_units': 'sum', 'production_created_units': 'sum'
    }).groupby('locale').mean().reset_index()

    def get_trimmed_aht(series):
        clean = series.dropna()
        return clean[clean <= clean.quantile(0.95)].mean() if not clean.empty else 0

    # --- TABS ---
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 Future Forecast Explorer"])

    # UI Generator Function to keep tabs looking identical
    def render_tables(is_forecast=False, week_label=None, week_idx=0):
        c1, c2 = st.columns(2)
        
        # Table 1: Workflow
        with c1:
            st.markdown(f"### 🛠️ Breakdown by Workflow {'(' + week_label + ')' if week_label else ''}")
            wf_list = []
            for _, row in wf_base.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
                if aht > 0:
                    tasks = row['audit_created_units'] * (1 + (site_growth_val * week_idx))
                    hc = (tasks * aht) / (3600 * prod_hours * 5)
                    data = {
                        "Workflow Name": row['workflow_name'],
                        "Tasks": int(tasks),
                        "Sampling %": f"{(row['audit_created_units']/row['production_created_units']*100):.1f}%" if not is_forecast else f"{hc:.2f} HC",
                        "Cleaned AHT (s)": f"{aht:.1f}" if not is_forecast else f"{qas_per_site - hc:.2f} Gap"
                    }
                    # Rename columns for Forecast tab to match your Screenshot layout
                    if is_forecast:
                        data = {"Workflow Name": data["Workflow Name"], "Expected Tasks": data["Tasks"], "HC Needed": data["Sampling %"], "Staffing Gap": data["Cleaned AHT (s)"]}
                    else:
                        data = {"Workflow Name": data["Workflow Name"], "Avg Weekly Tasks": data["Tasks"], "Sampling %": data["Sampling %"], "Cleaned AHT (s)": data["Cleaned AHT (s)"]}
                    wf_list.append(data)
            st.dataframe(pd.DataFrame(wf_list), use_container_width=True, hide_index=True)

        # Table 2: Locale
        with c2:
            st.markdown(f"### 📍 Breakdown by Locale {'(' + week_label + ')' if week_label else ''}")
            loc_list = []
            for _, row in loc_base.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
                if aht > 0:
                    tasks = row['audit_created_units'] * (1 + (site_growth_val * week_idx))
                    hc = (tasks * aht) / (3600 * prod_hours * 5)
                    data = {
                        "Locale": row['locale'],
                        "Tasks": int(tasks),
                        "Sampling %": f"{(row['audit_created_units']/row['production_created_units']*100):.1f}%" if not is_forecast else f"{hc:.2f} HC",
                        "Cleaned AHT (s)": f"{aht:.1f}" if not is_forecast else f"{qas_per_site - hc:.2f} Gap"
                    }
                    if is_forecast:
                        data = {"Locale": data["Locale"], "Expected Tasks": data["Tasks"], "HC Needed": data["Sampling %"], "Staffing Gap": data["Cleaned AHT (s)"]}
                    else:
                        data = {"Locale": data["Locale"], "Avg Weekly Tasks": data["Tasks"], "Sampling %": data["Sampling %"], "Cleaned AHT (s)": data["Cleaned AHT (s)"]}
                    loc_list.append(data)
            st.dataframe(pd.DataFrame(loc_list), use_container_width=True, hide_index=True)

    with tab1:
        render_tables(is_forecast=False)

    with tab2:
        st.caption(f"📅 **Current Date:** {datetime.now().strftime('%d %b %Y')}")
        week_options = []
        for i in range(1, 5):
            start = current_monday + timedelta(weeks=i)
            end = start + timedelta(days=4)
            week_options.append(f"Week {i} ({start.strftime('%d %b')} - {end.strftime('%d %b')})")
        
        selected_week = st.selectbox("Select Prediction Week:", week_options)
        render_tables(is_forecast=True, week_label=selected_week.split(' ')[0], week_idx=week_options.index(selected_week) + 1)

else:
    st.info("Please upload your Mercury and Quality Central CSV files.")
