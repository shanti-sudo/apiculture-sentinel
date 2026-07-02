"""
Apiculture Sentinel — Landing Page (Fleet Overview)
Entry point for the multi-page Streamlit app.
"""

import logging
import sys
from pathlib import Path

import streamlit as st

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger(__name__)

project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from frontend.database import get_fleet_summary, seed_fleet_database
from frontend.mcp_client import ensure_mcp_initialized

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Apiculture Sentinel",
    page_icon="🐝",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── One-time session initialization ────────────────────────────────────────────
server_path = Path(__file__).parent.parent / "servers" / "mcp_server.py"
ensure_mcp_initialized(server_path)

if "sentinel_memory" not in st.session_state:
    from agent.skills.sentinel_memory import SentinelMemory
    st.session_state.sentinel_memory = SentinelMemory()

if "history" not in st.session_state:
    st.session_state.history = []

if "selected_hive_id" not in st.session_state:
    st.session_state.selected_hive_id = None

if "fleet_seeded" not in st.session_state:
    with st.spinner("🌱 Initializing fleet database with 10,000 hives…"):
        seed_fleet_database()
    st.session_state.fleet_seeded = True

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Hero banner */
.hero-banner {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f4c2a 100%);
    border-radius: 20px;
    padding: 3rem 2.5rem;
    margin-bottom: 2rem;
    border: 1px solid rgba(255,255,255,0.08);
    position: relative;
    overflow: hidden;
}
.hero-banner::before {
    content: '';
    position: absolute;
    top: -50%;
    right: -10%;
    width: 400px;
    height: 400px;
    background: radial-gradient(circle, rgba(245,158,11,0.15) 0%, transparent 70%);
    border-radius: 50%;
}
.hero-title {
    font-size: 3.2rem;
    font-weight: 900;
    color: #f8fafc;
    letter-spacing: -1px;
    margin: 0;
    line-height: 1.1;
}
.hero-subtitle {
    font-size: 1.15rem;
    color: #94a3b8;
    margin-top: 0.75rem;
    font-weight: 400;
    max-width: 620px;
}
.hero-badge {
    display: inline-block;
    background: rgba(245,158,11,0.15);
    border: 1px solid rgba(245,158,11,0.4);
    color: #fbbf24;
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.3rem 0.8rem;
    border-radius: 20px;
    margin-bottom: 1rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

/* KPI cards */
.kpi-card {
    background: linear-gradient(135deg, #1e293b 0%, #162032 100%);
    border-radius: 16px;
    padding: 1.5rem 1.25rem;
    text-align: center;
    border: 1px solid rgba(255,255,255,0.07);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.kpi-card:hover {
    transform: translateY(-3px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.4);
}
.kpi-value {
    font-size: 2.8rem;
    font-weight: 800;
    line-height: 1;
    margin: 0.25rem 0;
}
.kpi-label {
    font-size: 0.85rem;
    font-weight: 500;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.kpi-total   .kpi-value { color: #e2e8f0; }
.kpi-healthy .kpi-value { color: #34d399; }
.kpi-warning .kpi-value { color: #fbbf24; }
.kpi-critical .kpi-value { color: #f87171; }

/* Nav cards */
.nav-card {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border-radius: 16px;
    padding: 2rem;
    border: 1px solid rgba(255,255,255,0.08);
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: center;
}
.nav-card:hover {
    border-color: rgba(245,158,11,0.5);
    box-shadow: 0 0 30px rgba(245,158,11,0.1);
}
.nav-card-icon { font-size: 2.5rem; margin-bottom: 0.75rem; }
.nav-card-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #f1f5f9;
    margin-bottom: 0.4rem;
}
.nav-card-desc { font-size: 0.875rem; color: #64748b; line-height: 1.5; }

/* Section divider */
.section-header {
    font-size: 0.75rem;
    font-weight: 700;
    color: #475569;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    margin: 2rem 0 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}
</style>
""", unsafe_allow_html=True)

# ── Hero Banner ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero-banner">
    <div class="hero-badge">🌍 Agents for Good · Agriculture & Food Supply</div>
    <div class="hero-title">🐝 Apiculture Sentinel</div>
    <div class="hero-subtitle">
        Agentic Edge AI for commercial beekeeping at scale. Monitoring
        <strong style="color:#fbbf24">10,000+ hives</strong> across 4 apiary sites
        using real-time IoT telemetry, acoustic AI classification, and
        multi-signal agentic reasoning.
    </div>
</div>
""", unsafe_allow_html=True)

# ── Fleet KPI Metrics ──────────────────────────────────────────────────────────
summary = get_fleet_summary()
st.markdown('<div class="section-header">Fleet Health Overview</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
kpis = [
    (c1, "kpi-total",    "🌐", summary["total"],    "Total Hives"),
    (c2, "kpi-healthy",  "✅", summary["healthy"],   "Healthy"),
    (c3, "kpi-warning",  "⚠️", summary["warnings"],  "Warnings"),
    (c4, "kpi-critical", "🔴", summary["critical"],  "Critical"),
]
for col, css_cls, icon, value, label in kpis:
    with col:
        st.markdown(f"""
        <div class="kpi-card {css_cls}">
            <div style="font-size:1.5rem">{icon}</div>
            <div class="kpi-value">{value:,}</div>
            <div class="kpi-label">{label}</div>
        </div>
        """, unsafe_allow_html=True)

# ── Health ratio bar ──────────────────────────────────────────────────────────
if summary["total"] > 0:
    pct_healthy = summary["healthy"] / summary["total"] * 100
    st.markdown("<br>", unsafe_allow_html=True)
    col_bar, col_pct = st.columns([5, 1])
    with col_bar:
        st.progress(int(pct_healthy) / 100, text=f"Fleet health: **{pct_healthy:.1f}%** hives operating normally")

# ── Navigation Cards ───────────────────────────────────────────────────────────
st.markdown('<div class="section-header">Operations Console</div>', unsafe_allow_html=True)

st.markdown("""
<style>
div[data-testid="stButton"]:has(button#fleet_nav_btn) button {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: 16px !important;
    padding: 2rem !important;
    height: auto !important;
    min-height: 140px !important;
    width: 100% !important;
    color: #f1f5f9 !important;
    text-align: center !important;
    transition: all 0.2s ease !important;
    cursor: pointer !important;
    white-space: normal !important;
    line-height: 1.5 !important;
}
div[data-testid="stButton"]:has(button#fleet_nav_btn) button:hover {
    border-color: rgba(245,158,11,0.5) !important;
    box-shadow: 0 0 30px rgba(245,158,11,0.1) !important;
    transform: translateY(-3px) !important;
}
</style>
""", unsafe_allow_html=True)

if st.button(
    "📡\n\n**Fleet Command Dashboard**\n\nLive triage queue for all anomalous hives. "
    "Filter by severity and site, view anomaly breakdowns, and drill into any hive for a full AI diagnostic.",
    key="fleet_nav_btn",
    use_container_width=True,
):
    st.switch_page("pages/fleet_command.py")

# ── Architecture overview ──────────────────────────────────────────────────────
st.markdown('<div class="section-header">System Architecture</div>', unsafe_allow_html=True)
with st.expander("🏛️ View Agent Architecture & Data Flow", expanded=False):
    st.markdown("""
    ```
    IoT Edge Sensors (10,000+ hives)
          │
          ▼
    [Edge AI Classification] → acoustic JSON payload
          │
          ▼
    ┌─────────────────────────────────────────┐
    │  Sentinel Reasoning Agent (ADK + Gemini) │
    │                                          │
    │  1. Perceive   → telemetry payload        │
    │  2. Contextualize → MCP weather server    │
    │  3. Remember   → SentinelMemory (history) │
    │  4. Evaluate   → confidence scoring       │
    │  5. Decide     → state classification     │
    │  6. Act        → Pub/Sub alert dispatch   │
    │  7. Persist    → write back to memory     │
    └─────────────────────────────────────────┘
          │
          ▼
    GCP Pub/Sub → Downstream Responders
    (Blanket request, Ventilation, Emergency inspection)
    ```
    """)

st.markdown("---")
st.markdown(
    "<p style='color:#334155;font-size:0.8rem;text-align:center'>"
    "Apiculture Sentinel · Google ADK · Gemini Flash · MCP · GCP Pub/Sub · "
    "Agents for Good Capstone 2026</p>",
    unsafe_allow_html=True,
)
