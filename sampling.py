import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- PAGE CONFIG ---
st.set_page_config(page_title="Strategic Capacity Planner", layout="wide")

# --- UI THEME ---
st.markdown("""
    <style>
    .stApp { background-color: #f8fafc !important; }
    div[data-testid="metric-container"] {
        background-color: #ffffff; border: 1px solid #e2e8f0;
        padding: 20px; border-radius: 12px;
    }
    .date-header { font-size: 1.1rem; font-weight: 600; color: #475569; }
    </style>
    """, unsafe_allow_html=True)

st.title("📊 Strategic Capacity Planner")

# --- SIDEBAR ---
st.sidebar.header("⚙️ Global Settings")
if st.sidebar.button("♻️ Reset All Data"):
    st.rerun()

merc_file = st.sidebar.file_uploader("Upload Mercury Metrics (AHT)", type="csv")
qc_file = st.sidebar.file_uploader("Upload Quality Central (Volume)", type="csv")

# UPDATED TOGGLE NAME
hide_ghosts = st.sidebar.toggle("🔍 Filter Active Workflows Only (AHT > 0)", value=True)

# UPDATED HEADCOUNT NAME
qas_per_site = st.sidebar.number_input("QA Available for the Week", min_value=0.1, value=10.0)
prod_hours = st.sidebar.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

# --- DATE HELPER ---
today = datetime.now()
next_monday = today + timedelta(days=(7 - today.weekday()) % 7)

def get_week_range(weeks_ahead):
    start = next_monday + timedelta(weeks=weeks_ahead-1)
    end = start + timedelta(days=4)
    return f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"

if merc_file and qc_file:
    # 1. LOAD & NORMALIZE
    df_m = pd.read_csv(merc_file)
    df_q = pd.read_csv(qc_file)

    for d in [df_m, df_q]:
        for col in d.columns:
            if d[col].dtype == 'object':
                d[col] = d[col].astype(str).str.strip()

    # 2. SITE & AUTO-LOCALE
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_site = st.sidebar.selectbox("Select Site:", all_sites, index=all_sites.index('CBG') if 'CBG' in all_sites else 0)
    site_locales = df_m[df_m['Column-1:Site'] == selected_site]['Column-2:Locale'].unique()
    
    f_m_base = df_m[df_m['Column-1:Site'] == selected_site]
    f_q_base = df_q[df_q['locale'].isin(site_locales)]

    # 3. STABLE GROWTH
    batch_cols = ['execution_batch_id', 'workflow_name', 'locale', 'Audit Creation Period Week']
    df_q_all_dedup = f_q_base.groupby(batch_cols).agg({'audit_created_units': 'first'}).reset_index()

    def get_stable_growth(data):
        if data.empty: return 0.0
        weekly_sum = data.groupby('Audit Creation Period Week')['audit_created_units'].sum().sort_index()
        u = weekly_sum.values
        if len(u) < 2: return 0.0
        diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
        return np.mean(diffs)

    stable_site_growth = get_stable_growth(df_q_all_dedup)
    st.sidebar.metric(label=f"📈 Stable Site Growth", value=f"{stable_site_growth * 100:.2f}%")

    # 4. PERFORMANCE CALCULATION
    f_m_base['Processed Units'] = pd.to_numeric(f_m_base['Processed Units'], errors='coerce').fillna(0)
    f_m_base['Processed Hours'] = pd.to_numeric(f_m_base['Processed Hours'], errors='coerce').fillna(0)
    f_m_base['Calc_AHT'] = 3600 * (f_m_base['Processed Hours'] + 
                                   pd.to_numeric(f_m_base['Manual Skip Hours'], errors='coerce').fillna(0)) / \
                                   f_m_base['Processed Units'].replace(0, np.nan)
    f_m_base['Calc_AHT'] = f_m_base['Calc_AHT'].fillna(0)

    real_workflows = f_m_base[f_m_base['Calc_AHT'] > 0]['Column-4:Transformation Type'].unique()

    # 5. FILTERING
    if hide_ghosts:
        f_q = f_q_base[f_q_base['workflow_name'].isin(real_workflows)]
        f_m = f_m_base[f_m_base['Column-4:Transformation Type'].isin(real_workflows)]
    else:
        f_q = f_q_base
        f_m = f_m_base

    # 6. BASELINE AGGREGATION
    df_q_final_dedup = f_q.groupby(batch_cols).agg({'audit_created_units': 'first', 'production_created_units': 'first'}).reset_index()
    num_weeks = 4
    all_weeks = sorted(df_q['Audit Creation Period Week'].unique(), reverse=True)
    recent_4_weeks = all_weeks[:4]
    qc_baseline = df_q_final_dedup[df_q_final_dedup['Audit Creation Period Week'].isin(recent_4_weeks)]

    def get_trimmed_aht(series):
        clean = series.dropna()
        return clean[clean <= clean.quantile(0.95)].mean() if not clean.empty else 0

    def color_gap(val):
        try: return 'color: red; font-weight: bold' if float(val) < 0 else 'color: green; font-weight: bold'
        except: return ''

    # --- TABS ---
    tab1, tab2 = st.tabs(["📊 Historical Audit Data", "🚀 Future Forecast Explorer"])

    with tab1:
        st.subheader(f"Historical Snapshot: {selected_site}")
        st.markdown(f"<p class='date-header'>Snapshot Date: {today.strftime('%b %d, %Y')}</p>", unsafe_allow_html=True)
        
        loc_agg = qc_baseline.groupby('locale').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
        loc_h = []
        for _, row in loc_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
            s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
            loc_h.append({"Locale": row['locale'], "Avg Weekly Units": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "AHT (Secs)": f"{aht:.1f}"})
        st.dataframe(pd.DataFrame(loc_h), use_container_width=True, hide_index=True)

        st.divider()

        wf_agg = qc_baseline.groupby('workflow_name').agg({'audit_created_units':'sum', 'production_created_units':'sum'}).reset_index()
        wf_h = []
        for _, row in wf_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
            s_pct = (row['audit_created_units']/row['production_created_units']*100) if row['production_created_units']>0 else 0
            wf_h.append({"Workflow Name": row['workflow_name'], "Avg Weekly Units": int(row['audit_created_units']/num_weeks), "Sampling %": f"{s_pct:.1f}%", "AHT (Secs)": f"{aht:.1f}"})
        st.dataframe(pd.DataFrame(wf_h), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader(f"Capacity Forecast: {selected_site}")
        week_labels = [f"Week {i} ({get_week_range(i)})" for i in range(1, 5)]
        selected_week_label = st.selectbox("Select Target Week:", week_labels)
        week_idx = week_labels.index(selected_week_label) + 1

        # PRE-CALC TOTALS FOR SUMMARY
        total_hc_needed = 0
        wf_f_list = []
        for _, row in wf_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
            pred = (row['audit_created_units']/num_weeks) * (1 + (stable_site_growth * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            if hc > 0 or not hide_ghosts:
                wf_f_list.append({"Workflow Name": row['workflow_name'], "Expected Units": int(pred), "HC Needed": hc, "Staffing Gap": qas_per_site - hc})
                total_hc_needed += hc

        # SUMMARY METRICS
        col1, col2, col3 = st.columns(3)
        col1.metric("Total HC Needed", f"{total_hc_needed:.2f}")
        col2.metric("QA Available", f"{qas_per_site:.2f}")
        col3.metric("Net Staffing Gap", f"{qas_per_site - total_hc_needed:.2f}", 
                   delta_color="normal")

        st.divider()

        st.markdown("#### 📍 Locale Prediction")
        loc_f = []
        for _, row in loc_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
            pred = (row['audit_created_units']/num_weeks) * (1 + (stable_site_growth * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            if hc > 0 or not hide_ghosts:
                loc_f.append({"Locale": row['locale'], "Expected Units": int(pred), "HC Needed": f"{hc:.2f}", "Staffing Gap": f"{qas_per_site - hc:.2f}"})
        st.dataframe(pd.DataFrame(loc_f).style.applymap(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)

        st.divider()

        st.markdown("#### 🛠️ Workflow Prediction")
        if wf_f_list:
            df_wf_f = pd.DataFrame(wf_f_list)
            df_wf_f['HC Needed'] = df_wf_f['HC Needed'].map('{:,.2f}'.format)
            df_wf_f['Staffing Gap'] = df_wf_f['Staffing Gap'].map('{:,.2f}'.format)
            st.dataframe(df_wf_f.style.applymap(color_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)
        else:
            st.warning("No active workflows match the current filters.")
else:
    st.info("Please upload Mercury Metrics and QC files to generate the capacity plan.")
