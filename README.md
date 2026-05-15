
# Capacity-Planning
# 📊 Strategic Capacity Planner
### Operational Excellence & Workforce Optimization Tool

A high-performance **Streamlit** application designed to bridge the gap between operational demand and workforce supply. This tool enables operations managers to perform data-driven capacity planning, ensuring Service Level Agreements (SLAs) are met through precise head-count (HC) forecasting.

## 🎯 Business Value
* **SLA Compliance:** Predicts potential staffing gaps up to 4 weeks in advance, allowing for proactive resource reallocation.
* **AHT Accuracy:** Implements trimmed-mean logic (95th percentile) for Average Handle Time (AHT) to remove statistical outliers.
* **Automated Forecasting:** Converts historical growth rates into future demand projections with zero manual calculation.

## 🏗️ Technical Highlights
* **Dynamic Forecast Engine:** Uses a rolling 4-week baseline and historical growth rates to project weekly volume.
* **Multi-Dimensional Analysis:** Three-layer insights covering Historical Snapshots, Forecast Explorers, and Strategic Demand Category views.
* **Automated Reporting:** Custom Excel engine (`xlsxwriter`) that exports 4-week projections into date-stamped, multi-sheet workbooks.

## 🧮 Core Logic
The tool calculates required staffing using the following capacity formula:

$$\text{Required HC} = \frac{(\text{Predicted Units} \times \text{Trimmed AHT}) / 3600}{\text{Daily Productive Hours} \times 5}$$

## 💻 Tech Stack
* **Frontend:** Streamlit
* **Data Processing:** Pandas, NumPy
* **Visualization:** Plotly Express
* **Reporting:** XlsxWriter
