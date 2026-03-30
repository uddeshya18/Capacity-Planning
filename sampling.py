import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
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

hide_ghosts = st.sidebar.toggle("Active Workflows", value=True)
qas_per_site = st.sidebar.number_input("QA Available", min_value=0.1, value=10.0)
prod_hours = st.sidebar.slider("Daily Productive Hours", 5.0, 9.0, 7.5)

# --- DATE HELPER ---
today = datetime.now()
next_monday = today + timedelta(days=(7 - today.weekday()) % 7)

def get_week_range(weeks_ahead):
    start = next_monday + timedelta(weeks=weeks_ahead-1)
    end = start + timedelta(days=4)
    return f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"

# --- STYLING HELPER ---
def style_staffing_gap(v):
    try:
        val = float(v)
        if val < 0:
            return 'color: #be123c; font-weight: bold; background-color: #fff1f2;'
        else:
            return 'color: #15803d; font-weight: bold; background-color: #f0fdf4;'
    except:
        return ''

if merc_file and qc_file:
    df_m = pd.read_csv(merc_file)
    df_q = pd.read_csv(qc_file)

    for d in [df_m, df_q]:
        for col in d.columns:
            if d[col].dtype == 'object':
                d[col] = d[col].astype(str).str.strip()

    # 1. SITE SELECTION
    all_sites = sorted(df_m['Column-1:Site'].unique())
    selected_sites = st.sidebar.multiselect("Select Sites:", options=all_sites, default=[all_sites[0]])

    if not selected_sites:
        st.warning("Please select at least one site.")
        st.stop()
    
    site_locales = df_m[df_m['Column-1:Site'].isin(selected_sites)]['Column-2:Locale'].unique()
    f_m_base = df_m[df_m['Column-1:Site'].isin(selected_sites)]
    f_q_base = df_q[df_q['locale'].isin(site_locales)]

    # 2. GROWTH CALC
    batch_cols = ['execution_batch_id', 'workflow_name', 'locale', 'Audit Creation Period Week']
    if 'demand_category' in f_q_base.columns:
        batch_cols.append('demand_category')

    df_q_all_dedup = f_q_base.groupby(batch_cols).agg({'audit_created_units': 'first'}).reset_index()

    def get_stable_growth(data):
        if data.empty: return 0.0
        weekly_sum = data.groupby('Audit Creation Period Week')['audit_created_units'].sum().sort_index()
        u = weekly_sum.values
        if len(u) < 2: return 0.0
        diffs = [(u[i] - u[i-1]) / u[i-1] for i in range(1, len(u)) if u[i-1] > 0]
        return np.mean(diffs)

    stable_site_growth = get_stable_growth(df_q_all_dedup)
    st.sidebar.metric(label="📈 Group Growth Rate", value=f"{stable_site_growth * 100:.2f}%")

    # 3. AHT CALC
    f_m_base['Processed Units'] = pd.to_numeric(f_m_base['Processed Units'], errors='coerce').fillna(0)
    f_m_base['Processed Hours'] = pd.to_numeric(f_m_base['Processed Hours'], errors='coerce').fillna(0)
    f_m_base['Calc_AHT'] = 3600 * (f_m_base['Processed Hours'] + pd.to_numeric(f_m_base['Manual Skip Hours'], errors='coerce').fillna(0)) / f_m_base['Processed Units'].replace(0, np.nan)
    f_m_base['Calc_AHT'] = f_m_base['Calc_AHT'].fillna(0)

    real_workflows = f_m_base[f_m_base['Calc_AHT'] > 0]['Column-4:Transformation Type'].unique()
    f_q = f_q_base[f_q_base['workflow_name'].isin(real_workflows)] if hide_ghosts else f_q_base
    f_m = f_m_base[f_m_base['Column-4:Transformation Type'].isin(real_workflows)] if hide_ghosts else f_m_base

    # 4. BASELINE DATA
    df_q_final_dedup = f_q.groupby(batch_cols).agg({'audit_created_units': 'first'}).reset_index()
    num_weeks = 4
    all_weeks = sorted(df_q['Audit Creation Period Week'].unique(), reverse=True)
    recent_4_weeks = all_weeks[:4]
    qc_baseline = df_q_final_dedup[df_q_final_dedup['Audit Creation Period Week'].isin(recent_4_weeks)]

    def get_trimmed_aht(series):
        clean = series.dropna()
        return clean[clean <= clean.quantile(0.95)].mean() if not clean.empty else 0

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["📊 Historical Data", "🚀 Forecast Explorer", "📂 Category View"])

    with tab1:
        st.subheader("Historical Performance Snapshot (Last 4 Weeks)")
        col_loc, col_wf = st.columns(2)
        with col_loc:
            st.markdown("#### 📍 Locale Baseline")
            loc_agg = qc_baseline.groupby('locale').agg({'audit_created_units':'sum'}).reset_index()
            loc_h = []
            for _, row in loc_agg.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
                loc_h.append({"Locale": row['locale'], "Avg Weekly Vol": int(row['audit_created_units']/num_weeks), "AHT (s)": round(aht, 1)})
            st.dataframe(pd.DataFrame(loc_h), use_container_width=True, hide_index=True)
        with col_wf:
            st.markdown("#### 🛠️ Workflow Baseline")
            wf_agg = qc_baseline.groupby('workflow_name').agg({'audit_created_units':'sum'}).reset_index()
            wf_h = []
            for _, row in wf_agg.iterrows():
                aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
                wf_h.append({"Workflow": row['workflow_name'], "Avg Weekly Vol": int(row['audit_created_units']/num_weeks), "AHT (s)": round(aht, 1)})
            st.dataframe(pd.DataFrame(wf_h), use_container_width=True, hide_index=True)

    with tab2:
        st.subheader("Future Capacity Projections")
        week_labels = [f"Week {i} ({get_week_range(i)})" for i in range(1, 5)]
        selected_week_label = st.selectbox("Target Forecast Week:", week_labels, key="tab2_week")
        week_idx = week_labels.index(selected_week_label) + 1

        st.markdown("#### 📍 Locale Prediction")
        loc_f = []
        for _, row in loc_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-2:Locale'] == row['locale']]['Calc_AHT'])
            pred = (row['audit_created_units']/num_weeks) * (1 + (stable_site_growth * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            loc_f.append({"Locale": row['locale'], "Expected Units": int(pred), "HC Needed": round(hc, 2), "Staffing Gap": round(qas_per_site - hc, 2)})
        st.dataframe(pd.DataFrame(loc_f).style.map(style_staffing_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("#### 🛠️ Workflow Prediction")
        wf_f = []
        for _, row in wf_agg.iterrows():
            aht = get_trimmed_aht(f_m[f_m['Column-4:Transformation Type'] == row['workflow_name']]['Calc_AHT'])
            pred = (row['audit_created_units']/num_weeks) * (1 + (stable_site_growth * week_idx))
            hc = (pred * aht) / (3600 * prod_hours * 5)
            wf_f.append({"Workflow": row['workflow_name'], "Expected Units": int(pred), "HC Needed": round(hc, 2), "Staffing Gap": round(qas_per_site - hc, 2)})
        st.dataframe(pd.DataFrame(wf_f).style.map(style_staffing_gap, subset=['Staffing Gap']), use_container_width=True, hide_index=True)

    with tab3:
        st.subheader("📂 Strategic Demand Overview")
        
        # --- WEEK SELECTOR ADDED TO TAB 3 ---
        week_labels_t3 = [f"Week {i} ({get_week_range(i)})" for i in range(1, 5)]
        selected_week_t3 = st.selectbox("Select Forecast Week for Category View:", week_labels_t3, key="tab3_week")
        week_idx_t3 = week_labels_t3.index(selected_week_t3) + 1
        
        actual_categories = ["Classic Alexa", "Nova", "Alexa+", "Other"]
        
        if 'demand_category' in qc_baseline.columns:
            hier_data = qc_baseline.groupby(['demand_category', 'workflow_name']).agg({'audit_created_units':'sum'}).reset_index()
            hier_data = hier_data[hier_data['demand_category'].isin(actual_categories)]
            
            # Recalculate 'Tasks Remaining' based on Tab 3's week selection
            hier_data['Tasks Remaining'] = ((hier_data['audit_created_units']/num_weeks) * (1 + (stable_site_growth * week_idx_t3))).astype(int)

            fig = px.treemap(
                hier_data,
                path=[px.Constant("All Demand"), 'demand_category', 'workflow_name'],
                values='Tasks Remaining',
                color='demand_category',
                color_discrete_map={
                    "Classic Alexa": "#1E40AF", 
                    "Nova": "#B91C1C",          
                    "Alexa+": "#047857",        
                    "Other": "#6D28D9"           
                },
                title=f"Demand Bifurcation for {selected_week_t3}"
            )
            
            fig.update_traces(
                textinfo="label+value",
                marker=dict(line=dict(width=2, color='white'))
            )
            
            st.plotly_chart(fig, use_container_width=True)

            st.markdown(f"#### 📋 Detailed Breakdown for {selected_week_t3}")
            st.dataframe(
                hier_data[['demand_category', 'workflow_name', 'Tasks Remaining']].sort_values(['demand_category', 'Tasks Remaining'], ascending=[True, False]),
                use_container_width=True, hide_index=True
            )
        else:
            st.info("Demand Category column not detected.")

else:
    st.info("Upload Mercury and QC files to begin.")
