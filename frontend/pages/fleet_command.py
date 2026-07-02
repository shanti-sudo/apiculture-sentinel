"""
Fleet Command Dashboard — pages/fleet_command.py
Interactive triage queue for all anomalous hives.
"""

import sys
from pathlib import Path

import streamlit as st

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from frontend.database import (
    get_active_alerts,
    get_all_sites,
    get_anomaly_counts_by_site,
    get_anomaly_counts_by_type,
    get_fleet_summary,
)

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Fleet Command · Apiculture Sentinel",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.page-header {
    background: linear-gradient(135deg, #0f172a 0%, #1a2744 100%);
    border-radius: 14px;
    padding: 1.5rem 2rem;
    margin-bottom: 1.5rem;
    border: 1px solid rgba(255,255,255,0.07);
    display: flex;
    align-items: center;
    gap: 1rem;
}
.page-header h1 { font-size: 1.8rem; font-weight: 800; color: #f1f5f9; margin: 0; }
.page-header p  { font-size: 0.9rem; color: #64748b; margin: 0.25rem 0 0; }

.kpi-mini {
    background: #1e293b;
    border-radius: 12px;
    padding: 1rem 1.25rem;
    border: 1px solid rgba(255,255,255,0.06);
    text-align: center;
}
.kpi-mini-val  { font-size: 2rem; font-weight: 800; margin: 0; }
.kpi-mini-lbl  { font-size: 0.78rem; color: #64748b; font-weight: 500;
                  text-transform: uppercase; letter-spacing: 0.08em; }

.chart-card {
    background: #1e293b;
    border-radius: 14px;
    padding: 1.25rem;
    border: 1px solid rgba(255,255,255,0.06);
}
.chart-title { font-size: 0.85rem; font-weight: 600; color: #94a3b8;
               text-transform: uppercase; letter-spacing: 0.08em;
               margin-bottom: 0.75rem; }

.severity-CRITICAL { color: #f87171; font-weight: 700; }
.severity-HIGH     { color: #fbbf24; font-weight: 600; }
.severity-MEDIUM   { color: #60a5fa; font-weight: 600; }

.inspect-banner {
    background: linear-gradient(90deg, #1e3a5f, #1a2744);
    border: 1px solid rgba(96,165,250,0.3);
    border-radius: 12px;
    padding: 1rem 1.5rem;
    margin-top: 1rem;
    display: flex;
    align-items: center;
    gap: 1rem;
}
</style>
""", unsafe_allow_html=True)

# ── Page Header ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-header">
    <div style="font-size:2.5rem">📡</div>
    <div>
        <h1>Fleet Command Dashboard</h1>
        <p>Real-time anomaly triage across 10,000+ hives · 4 apiary sites</p>
    </div>
</div>
""", unsafe_allow_html=True)

nav1, _spacer = st.columns([1, 5])
with nav1:
    if st.button("← Home", use_container_width=True):
        st.switch_page("home_landing.py")

st.markdown("---")

# ── KPI Row ────────────────────────────────────────────────────────────────────
summary = get_fleet_summary()
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""
    <div class="kpi-mini">
        <div class="kpi-mini-val" style="color:#e2e8f0">{summary["total"]:,}</div>
        <div class="kpi-mini-lbl">🌐 Total Hives</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div class="kpi-mini">
        <div class="kpi-mini-val" style="color:#34d399">{summary["healthy"]:,}</div>
        <div class="kpi-mini-lbl">✅ Healthy</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""
    <div class="kpi-mini">
        <div class="kpi-mini-val" style="color:#fbbf24">{summary["warnings"]:,}</div>
        <div class="kpi-mini-lbl">⚠️ Warnings</div>
    </div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""
    <div class="kpi-mini">
        <div class="kpi-mini-val" style="color:#f87171">{summary["critical"]:,}</div>
        <div class="kpi-mini-lbl">🔴 Critical</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ── Charts Row ─────────────────────────────────────────────────────────────────
chart_col, type_col = st.columns([3, 2])

with chart_col:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True)
    st.markdown('<div class="chart-title">📊 Anomalies by Apiary Site</div>', unsafe_allow_html=True)
    site_df = get_anomaly_counts_by_site()
    if not site_df.empty:
        st.bar_chart(
            site_df.set_index("site")["anomaly_count"],
            color="#f87171",
            height=220,
        )
    else:
        st.info("No anomalies detected across the fleet.")
    st.markdown('</div>', unsafe_allow_html=True)

with type_col:
    st.markdown('<div class="chart-card">', unsafe_allow_html=True)
    st.markdown('<div class="chart-title">🗂️ Alert Breakdown by Type</div>', unsafe_allow_html=True)
    type_df = get_anomaly_counts_by_type()
    if not type_df.empty:
        SEVERITY_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🔵"}
        for _, row in type_df.iterrows():
            em = SEVERITY_EMOJI.get(row["severity"], "⚪")
            pct = row["count"] / max(summary["total"], 1) * 100
            st.markdown(
                f"{em} **{row['state']}**  \n"
                f"<small style='color:#64748b'>{row['count']} hives · {pct:.2f}% · {row['severity']}</small>",
                unsafe_allow_html=True,
            )
            st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")

# ── Filters Sidebar ────────────────────────────────────────────────────────────
st.sidebar.header("🎛️ Triage Filters")
all_sites = get_all_sites()
severity_filter = st.sidebar.multiselect(
    "Severity",
    options=["CRITICAL", "HIGH", "MEDIUM"],
    default=["CRITICAL", "HIGH", "MEDIUM"],
)
site_filter = st.sidebar.multiselect(
    "Apiary Site",
    options=all_sites,
    default=all_sites,
)
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Reseed Fleet Database"):
    from frontend.database import seed_fleet_database
    with st.spinner("Re-seeding fleet…"):
        seed_fleet_database(force=True)
    st.rerun()


col_alerts, col_spatial = st.columns([3, 2])

with col_alerts:
    st.markdown("### 🚨 Active Triage Queue")
    queue_df = get_active_alerts(
        severity_filter=severity_filter if severity_filter else None,
        site_filter=site_filter if site_filter else None,
    )

    if queue_df.empty:
        st.success("✅ No anomalies match the current filter criteria.")
    else:
        st.caption(f"Showing **{len(queue_df)}** anomalous hives · Click a row then press **Inspect Hive ↗**")

        display_df = queue_df[[
            "hive_id", "site", "state", "severity",
            "internal_temp_c", "hive_weight_kg",
            "edge_acoustic_classification", "action", "last_eval_ts"
        ]].rename(columns={
            "hive_id": "Hive ID",
            "site": "Site",
            "state": "State",
            "severity": "Severity",
            "internal_temp_c": "Int. Temp (°C)",
            "hive_weight_kg": "Weight (kg)",
            "edge_acoustic_classification": "Acoustic",
            "action": "Required Action",
            "last_eval_ts": "Last Evaluated",
        })

        event = st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            height=420,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "Severity": st.column_config.TextColumn("Severity", width="small"),
                "Int. Temp (°C)": st.column_config.NumberColumn("Int. Temp (°C)", format="%.1f °C"),
                "Weight (kg)": st.column_config.NumberColumn("Weight (kg)", format="%.1f kg"),
            },
        )

        # ── Inspect Hive action ────────────────────────────────────────────────────
        selected_rows = event.selection.get("rows", [])
        if selected_rows:
            row_idx = selected_rows[0]
            selected_hive = queue_df.iloc[row_idx]
            hive_id = selected_hive["hive_id"]

            st.markdown(f"""
            <div class="inspect-banner">
                <div style="font-size:1.8rem">🔍</div>
                <div>
                    <strong style="color:#f1f5f9">{hive_id}</strong>
                    <span style="color:#64748b"> · {selected_hive['site']} · </span>
                    <span style="color:#f87171;font-weight:700">{selected_hive['severity']}</span>
                    <span style="color:#94a3b8"> — {selected_hive['state']}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            if st.button(f"🔬 Inspect Hive {hive_id}", type="primary", use_container_width=False):
                st.session_state.selected_hive_id = hive_id
                st.switch_page("pages/hive_triage.py")

with col_spatial:
    st.markdown("### 🌍 Apiary Site Spatial Compliance")
    st.caption("Asynchronous layout and clearance audits of physical apiary locations.")

    from agent.skills.spatial_manager import ApiarySpatialManager

    mock_site_layouts = {
        "North_Field": {
            "total_sq_ft": 200.0,
            "hives": [
                {"hive_id": "H-00001", "clearance_front_ft": 5.5, "clearance_back_ft": 3.0, "clearance_sides_ft": 3.0},
                {"hive_id": "H-00002", "clearance_front_ft": 6.0, "clearance_back_ft": 3.5, "clearance_sides_ft": 4.0},
            ],
        },
        "East_Ridge": {
            "total_sq_ft": 150.0,
            "hives": [
                {"hive_id": "H-00101", "clearance_front_ft": 5.0, "clearance_back_ft": 3.0, "clearance_sides_ft": 3.0},
            ],
        },
        "South_Grove": {
            "total_sq_ft": 120.0,
            "hives": [
                {"hive_id": "H-00201", "clearance_front_ft": 6.5, "clearance_back_ft": 3.0, "clearance_sides_ft": 3.0},
            ],
        },
        "West_Valley_04": {
            "total_sq_ft": 80.0,
            "hives": [
                {"hive_id": "H-00301", "clearance_front_ft": 4.0, "clearance_back_ft": 3.0, "clearance_sides_ft": 3.0}, # Front clearance too low
                {"hive_id": "H-00302", "clearance_front_ft": 5.5, "clearance_back_ft": 2.5, "clearance_sides_ft": 2.8}, # Back & Side too low
            ],
        },
    }

    spatial_mgr = ApiarySpatialManager()
    audit_results = {}
    for site_name, layout in mock_site_layouts.items():
        audit_results[site_name] = spatial_mgr.validate_layout(layout)

    for site_name, result in audit_results.items():
        status = result["status"]
        status_emoji = "🟢 COMPLIANT" if status == "COMPLIANT" else "🔴 VIOLATION"

        with st.expander(f"{site_name} — {status_emoji}", expanded=(status != "COMPLIANT")):
            st.markdown(f"**Total Area:** {result['total_sq_ft']:.1f} sq. ft.")
            st.markdown(f"**Hives Count:** {result['num_hives']} / {result['max_hives']} max")

            if status == "COMPLIANT":
                st.success("All placement clearances and capacity requirements met.")
            else:
                st.error("Clearance violations detected:")
                for violation in result.get("violations", []):
                    hive_id = violation.get("hive_id", "unknown")
                    if hive_id == "apiary":
                        st.warning(violation["reasons"][0])
                    else:
                        for reason in violation.get("reasons", []):
                            st.markdown(f"- **{hive_id}**: {reason}")
