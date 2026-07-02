"""
Node Triage Lab — pages/hive_triage.py
Standalone single-hive diagnostic workbench.
Pre-populates from fleet database when navigated via Fleet Command.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import streamlit as st

project_root = str(Path(__file__).parent.parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from agent.skills.state_evaluator import evaluate_hive_state
from agent.skills.weather_provider import MCPWeatherProvider
from frontend.mcp_client import (
    ensure_mcp_initialized,
    get_mcp_environmental_context,
)

logger = logging.getLogger(__name__)

# Centralized fallback defaults configuration
DEFAULT_HIVE_STATE = {
    "internal_temp_c": 35.0,
    "hive_weight_kg": 50.0,
    "edge_acoustic_classification": "STEADY_HUM",
    "external_temp_c": 25.0,
    "conditions": "Partly Cloudy",
    "humidity": 50.0,
    "wind_speed_kmh": 10.0
}

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Node Triage · Apiculture Sentinel",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── MCP & session initialization ───────────────────────────────────────────────
server_path = Path(__file__).parent.parent.parent / "servers" / "mcp_server.py"
ensure_mcp_initialized(server_path)

if "sentinel_memory" not in st.session_state:
    from agent.skills.sentinel_memory import SentinelMemory
    st.session_state.sentinel_memory = SentinelMemory()

for key, default in [
    ("edge_acoustic_classification", "STEADY_HUM"),
    ("weather_conditions", "Partly Cloudy"),
    ("int_temp", 35.0),
    ("ext_temp", 20.0),
    ("weight", 40.0),
    ("history", []),
    ("pubsub_warning", None),
    ("mcp_dirty", False),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ── Pre-load from fleet when navigated via "Inspect Hive" ─────────────────────
fleet_hive_id = st.session_state.get("selected_hive_id")

if not fleet_hive_id:
    st.warning("⚠️ No hive selected for triage. Please select a hive from the Fleet Command Dashboard.")
    if st.button("📡 Go to Fleet Command Dashboard", type="primary"):
        st.switch_page("pages/fleet_command.py")
    st.stop()

fleet_hive_data: dict = {}
from frontend.database import get_hive_telemetry

fleet_hive_data = get_hive_telemetry(fleet_hive_id)

# Only stamp session state from database on first-time load of this hive
if st.session_state.get("loaded_hive_id") != fleet_hive_id:
    if not isinstance(fleet_hive_data, dict):
        fleet_hive_data = {}
    acoustic_val = fleet_hive_data.get("edge_acoustic_classification")
    if acoustic_val == "NORMAL":
        acoustic_val = "STEADY_HUM"
    if acoustic_val not in ["STEADY_HUM", "PIPING_DETECTED", "ERRATIC_MITE_STRESS", "MOURNING_ROAR", "QUIESCENT"]:
        acoustic_val = DEFAULT_HIVE_STATE["edge_acoustic_classification"]
    st.session_state["edge_acoustic_classification"] = acoustic_val
    st.session_state["int_temp"] = float(fleet_hive_data.get("internal_temp_c") if fleet_hive_data.get("internal_temp_c") is not None else DEFAULT_HIVE_STATE["internal_temp_c"])
    st.session_state["ext_temp"] = float(fleet_hive_data.get("external_temp_c") if fleet_hive_data.get("external_temp_c") is not None else DEFAULT_HIVE_STATE["external_temp_c"])
    st.session_state["weight"]   = float(fleet_hive_data.get("hive_weight_kg") if fleet_hive_data.get("hive_weight_kg") is not None else DEFAULT_HIVE_STATE["hive_weight_kg"])
    st.session_state["weather_conditions"] = fleet_hive_data.get("conditions") if fleet_hive_data.get("conditions") is not None else DEFAULT_HIVE_STATE["conditions"]

    # Automatically write this hive's initial state to the MCP weather simulation file
    WEATHER_STATE_FILE = Path(project_root) / "simulated_data" / "weather_state.json"
    try:
        WEATHER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        humidity = 50.0
        wind_speed_kmh = 10.0
        if WEATHER_STATE_FILE.exists():
            try:
                with open(WEATHER_STATE_FILE, "r", encoding="utf-8") as rf:
                    existing = json.load(rf)
                    humidity = existing.get("humidity", 50.0)
                    wind_speed_kmh = existing.get("wind_speed_kmh", 10.0)
            except Exception:
                pass
        with open(WEATHER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "external_temp_c": st.session_state["ext_temp"],
                "conditions": st.session_state["weather_conditions"],
                "humidity": humidity,
                "wind_speed_kmh": wind_speed_kmh
            }, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to initialize weather state file: {e}")

    # Seed SentinelMemory with current telemetry state from database as initial baseline observation
    from agent.skills.sentinel_memory import SentinelMemory
    mem = SentinelMemory()
    last_state = fleet_hive_data.get("state", "INITIALIZING_MONITORING")
    mem.observations.append({
        "timestamp": fleet_hive_data.get("last_eval_ts") or datetime.datetime.now().isoformat(),
        "state": last_state,
        "explanation": "Loaded baseline from database",
        "telemetry": {
            "edge_acoustic_classification": acoustic_val,
            "environmental_metrics": {
                "internal_temp_c": st.session_state["int_temp"]
            },
            "weight_metrics": {
                "hive_weight_kg": st.session_state["weight"]
            }
        }
    })
    st.session_state.sentinel_memory = mem

    st.session_state["mcp_dirty"] = False
    st.session_state["loaded_hive_id"] = fleet_hive_id
    if "evaluation_result" in st.session_state:
        del st.session_state["evaluation_result"]
    if "evaluation_success" in st.session_state:
        del st.session_state["evaluation_success"]

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;900&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.page-header {
    background: linear-gradient(135deg, #0f172a 0%, #1a2744 100%);
    border-radius: 14px;
    padding: 1.25rem 1.75rem;
    margin-bottom: 1.25rem;
    border: 1px solid rgba(255,255,255,0.07);
}
.page-header h1 { font-size: 1.7rem; font-weight: 800; color: #f1f5f9; margin: 0; }
.page-header p  { font-size: 0.875rem; color: #64748b; margin: 0.2rem 0 0; }

.fleet-banner {
    background: linear-gradient(90deg, #0c2340, #122944);
    border: 1px solid rgba(96,165,250,0.35);
    border-radius: 12px;
    padding: 1rem 1.5rem;
    margin-bottom: 1.25rem;
}
.fleet-banner-id   { font-size: 1.4rem; font-weight: 800; color: #93c5fd; }
.fleet-banner-meta { font-size: 0.85rem; color: #64748b; margin-top: 0.2rem; }
</style>
""", unsafe_allow_html=True)

# ── Educational Details ────────────────────────────────────────────────────────
STATE_DETAILS = {
    "PEST_DISTRESS_VARROA": {
        "title": "🦟 Varroa Mite Infestation Distress",
        "why": "High-amplitude acoustic spikes combined with erratic frequencies indicate frantic grooming and wing-fanning — a classic sign of severe mite parasitism.",
        "action_steps": [
            "Perform a powdered sugar shake test or alcohol wash to verify mite density.",
            "If mite counts exceed the threshold (2–3 mites per 100 bees), apply approved treatments (formic acid, thymol, or oxalic acid vapor).",
            "Ensure the entrance is restricted and the hive is well-ventilated during chemical treatments.",
        ],
    },
    "COLD_STRESS_ALERT": {
        "title": "🥶 Hive Cold Stress",
        "why": "External conditions have dropped below freezing and the internal hive temperature is below 33 °C. The bees are struggling to maintain the critical brood nesting temperature (34–35 °C).",
        "action_steps": [
            "Wrap the hive with insulated wraps or tar paper to block drafts.",
            "Insert an entrance reducer to limit cold air intake.",
            "Ensure emergency sugar candy or fondant boards are placed directly above the winter cluster.",
        ],
    },
    "PRE_SWARMING_ALERT": {
        "title": "👑 Pre-Swarming Congestion",
        "why": "A high-pitch piping sound profile (frequency > 240 Hz) indicates virgin queen piping or severe crowding, signaling imminent swarm departure.",
        "action_steps": [
            "Inspect the hive immediately for active swarm queen cells (usually on frame bottoms).",
            "Perform an artificial colony split, or add a new hive body / honey super to expand capacity.",
        ],
    },
    "QUEENLESS_COLONY": {
        "title": "😢 Queenless 'Mourning Roar'",
        "why": "A low, persistent wailing hum (~220 Hz) indicates the lack of queen pheromones, causing stress, confusion, and defensiveness.",
        "action_steps": [
            "Check frames thoroughly for eggs or day-old larvae to confirm the absence of a laying queen.",
            "Introduce a mated caged queen, or insert a frame of fresh brood from a healthy donor hive.",
        ],
    },
    "CATASTROPHIC_MASS_LOSS": {
        "title": "🚨 Catastrophic Mass Loss / Physical Security Alert",
        "why": "A massive, sudden weight drop (> 5.0 kg) deviates completely from biological swarming behavior — it suggests theft, a predator attack, or a sensor failure.",
        "action_steps": [
            "Dispatch an emergency physical inspection of the apiary immediately.",
            "Check for physical damage to hive bodies, stands, or fencing (potential bear activity).",
            "Verify scale hardware and power connections to rule out sensor malfunction.",
        ],
    },
    "SWARM_DEPARTURE_DETECTED": {
        "title": "🚀 Swarm Departure Event",
        "why": "A sudden weight drop of −1.5 to −5.0 kg indicates ~50–60 % of the colony bees have swarmed with the old queen.",
        "action_steps": [
            "Search nearby trees, bushes, or structures for the resting swarm cluster.",
            "Place a capture box or swarm trap with old comb or lemongrass lure nearby.",
            "Inspect the parent hive to ensure emerging queen cells are left behind.",
        ],
    },
    "HEAT_STRESS_ALERT": {
        "title": "🥵 Hive Heat Stress",
        "why": "Internal hive temperature has risen above 37 °C. The bees are struggling to cool the brood nest via wing-fanning and foraging for water.",
        "action_steps": [
            "Ensure the hive has adequate ventilation (remove entrance reducers or open screened bottom boards).",
            "Provide a clean source of water nearby for evaporative cooling.",
            "Add temporary shade to protect the hive from direct mid-day sun.",
        ],
    },
    "CRITICAL_HEAT_ALERT": {
        "title": "🔥 Critical Brood Damage Alert",
        "why": "Internal temperature has exceeded 40 °C, threatening to melt wax comb and cause permanent damage to developing brood larvae.",
        "action_steps": [
            "Immediately shade the hive from direct sunlight.",
            "Provide emergency cooling by misting or placing ice packs on the hive cover.",
            "Ensure full ventilation options are open.",
        ],
    },
}

# ── Page Header ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-header">
    <h1>🔬 Hive Triage</h1>
    <p>Single-hive AI diagnostic workbench · Sentinel reasoning engine</p>
</div>
""", unsafe_allow_html=True)



# ── Fleet-loaded banner ────────────────────────────────────────────────────────
if fleet_hive_id and fleet_hive_data:
    site = fleet_hive_data.get("site", "—")
    state = fleet_hive_data.get("state", "—")
    severity = fleet_hive_data.get("severity", "—")
    SEVERITY_COLOR = {"CRITICAL": "#f87171", "HIGH": "#fbbf24", "MEDIUM": "#60a5fa", "INFO": "#34d399"}
    sev_color = SEVERITY_COLOR.get(severity, "#94a3b8")
    st.markdown(f"""
    <div class="fleet-banner">
        <div style="font-size:0.75rem;color:#475569;font-weight:600;
                    text-transform:uppercase;letter-spacing:.08em;margin-bottom:.35rem">
            📡 Loaded from Fleet Command
        </div>
        <div class="fleet-banner-id">{fleet_hive_id}</div>
        <div class="fleet-banner-meta">
            Site: <strong style="color:#cbd5e1">{site}</strong> ·
            Last state: <strong style="color:{sev_color}">{state}</strong> ·
            Severity: <strong style="color:{sev_color}">{severity}</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)

    pass

st.markdown("---")

# ── Sidebar ────────────────────────────────────────────────────────────────────
st.sidebar.header("Telemetry Input (Mock)")


def make_dirty():
    st.session_state.mcp_dirty = True
    if "evaluation_result" in st.session_state:
        del st.session_state["evaluation_result"]
    if "evaluation_success" in st.session_state:
        del st.session_state["evaluation_success"]


edge_acoustic_classification = st.sidebar.selectbox(
    "Edge Audio Sensor (Simulated)",
    ["STEADY_HUM", "PIPING_DETECTED", "ERRATIC_MITE_STRESS", "MOURNING_ROAR", "QUIESCENT"],
    key="edge_acoustic_classification",
    on_change=make_dirty,
)
st.sidebar.caption("Simulates TinyML edge classification to preserve bandwidth and battery.")
with st.sidebar.expander("ℹ️ Audio Profiles Explained"):
    st.markdown("""
    * **STEADY_HUM** — Normal acoustic baseline of a healthy colony.
    * **PIPING_DETECTED** — Queen piping; indicates swarming prep.
    * **ERRATIC_MITE_STRESS** — Colony stress pattern from mite infestation.
    * **MOURNING_ROAR** — Wailing hum signaling queenlessness.
    * **QUIESCENT** — Extreme quiet; may follow swarm departure.
    """)

weather_conditions = st.sidebar.selectbox(
    "🌍 MCP Weather Context (Simulated)",
    ["Sunny", "Partly Cloudy", "Overcast", "Rainy"],
    key="weather_conditions",
    on_change=make_dirty,
)

int_temp = st.sidebar.slider("Internal Temp (°C)", 20.0, 45.0, key="int_temp", on_change=make_dirty)

try:
    thresholds_path = Path(project_root) / "simulated_data" / "temperature_thresholds.json"
    with open(thresholds_path, encoding="utf-8") as f:
        thresholds_data = json.load(f)
    normal_range = thresholds_data.get("brood_temperature_c", {}).get("normal", "32-36")
    t_min, t_max = map(float, normal_range.split("-"))
except Exception:
    t_min, t_max = 32.0, 36.0

slider_color = "#1f77b4" if (t_min <= int_temp <= t_max) else "#ff4b4b"
st.sidebar.markdown(
    f"""<style>
    .st-key-int_temp [data-testid="stWidgetLabel"] p,
    .st-key-int_temp div {{ color: {slider_color} !important; }}
    .st-key-int_temp [data-testid="stSliderTrack"] {{
        background: {slider_color} !important;
        background-color: {slider_color} !important;
    }}
    .st-key-int_temp [role="slider"] {{
        background-color: {slider_color} !important;
        box-shadow: 0px 0px 0px 0.2rem {slider_color}33 !important;
    }}
    </style>""",
    unsafe_allow_html=True,
)

ext_temp = st.sidebar.slider("External Temp (°C)", -10.0, 40.0, key="ext_temp", on_change=make_dirty)
weight    = st.sidebar.slider("Hive Weight (kg)", 10.0, 60.0,  key="weight",    on_change=make_dirty)

st.sidebar.markdown("---")
if st.sidebar.button("Clear Sentinel Memory"):
    from agent.skills.sentinel_memory import SentinelMemory
    st.session_state.sentinel_memory = SentinelMemory()
    st.session_state.history = []
    st.sidebar.success("Sentinel Memory Cleared!")
    st.rerun()

demo_mode = st.sidebar.checkbox(
    "🚀 Interactive Demo Mode (Bypass Temporal Persistence)",
    value=False,
    key="demo_mode",
)

# ── MCP State File ─────────────────────────────────────────────────────────────
WEATHER_STATE_FILE = Path(project_root) / "simulated_data" / "weather_state.json"
WEATHER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

if st.sidebar.button("Update MCP Context"):
    st.session_state.mcp_dirty = False
    try:
        humidity = 50.0
        wind_speed_kmh = 10.0
        if WEATHER_STATE_FILE.exists():
            try:
                with open(WEATHER_STATE_FILE, "r", encoding="utf-8") as rf:
                    existing = json.load(rf)
                    humidity = existing.get("humidity", 50.0)
                    wind_speed_kmh = existing.get("wind_speed_kmh", 10.0)
            except Exception:
                pass
        with open(WEATHER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "external_temp_c": ext_temp,
                "conditions": weather_conditions,
                "humidity": humidity,
                "wind_speed_kmh": wind_speed_kmh
            }, f, indent=4)
        st.sidebar.success("MCP State Updated!")
        st.rerun()
    except Exception as e:
        st.sidebar.warning(f"System Warning: Failed to update MCP state file: {e}")

# ── Main Layout ────────────────────────────────────────────────────────────────
col1, col2 = st.columns([1, 1])

with col1:
    st.markdown("### 🌡️ Current MCP Environmental Status")
    try:
        current_mcp_context = asyncio.run(get_mcp_environmental_context())
        manager = st.session_state.get("mcp_manager")
        if not manager or not manager.session or manager.error:
            st.warning("⚠️ MCP Weather Server unavailable. Using safe-state fallback values.")
    except Exception as e:
        fallback_ext_temp = DEFAULT_HIVE_STATE["external_temp_c"]
        fallback_conditions = DEFAULT_HIVE_STATE["conditions"]
        loaded_from_file = False
        try:
            with open(WEATHER_STATE_FILE, "r", encoding="utf-8") as rf:
                current_mcp_context = json.load(rf)
                if current_mcp_context.get("external_temp_c") is not None:
                    loaded_from_file = True
        except Exception:
            pass
            
        if not loaded_from_file:
            current_mcp_context = {
                "external_temp_c": fallback_ext_temp,
                "conditions": fallback_conditions,
                "humidity": DEFAULT_HIVE_STATE["humidity"],
                "wind_speed_kmh": DEFAULT_HIVE_STATE["wind_speed_kmh"],
            }
            try:
                with open(WEATHER_STATE_FILE, "w", encoding="utf-8") as wf:
                    json.dump(current_mcp_context, wf, indent=4)
            except Exception as write_err:
                logger.error(f"Failed to write fallback weather state: {write_err}")
        st.warning(f"⚠️ Could not fetch MCP context: {e}")

    m1, m2 = st.columns(2)
    m1.metric("Internal Temp (°C)", f"{int_temp} °C")
    m2.metric("External Temp (°C)", f"{current_mcp_context.get('external_temp_c')} °C")
    st.info(
        f"**MCP Weather Context**: {current_mcp_context.get('conditions')}, "
        f"Humidity: {current_mcp_context.get('humidity')}%, "
        f"Wind: {current_mcp_context.get('wind_speed_kmh')} km/h"
    )

    st.markdown("---")
    st.markdown("### 📊 Active Telemetry Payload")

    telemetry_data = {
        "hive_id": fleet_hive_id,
        "edge_acoustic_classification": edge_acoustic_classification,
        "acoustic_metrics": {"edge_acoustic_classification": edge_acoustic_classification},
        "environmental_metrics": {
            "internal_temp_c": int_temp,
            "external_temp_c": current_mcp_context.get("external_temp_c"),
        },
        "weight_metrics": {"hive_weight_kg": weight},
    }
    st.json(telemetry_data)

    if st.session_state.get("mcp_dirty", False):
        st.warning("⚠️ Parameters have changed! Click **Update MCP Context** in the sidebar first.")

    if st.button("Evaluate Hive State", disabled=st.session_state.get("mcp_dirty", False)):
        with st.status("Running Diagnostic Flow...", expanded=False) as status:
            async def run_evaluation():
                st.write("Fetching environmental context from MCP Server...")
                env_context = await get_mcp_environmental_context()
                st.write(f"Fetched MCP Environmental Context: {env_context}")

                st.write("Analyzing patterns via State Evaluator...")
                manager = st.session_state.get("mcp_manager")
                mcp_session = manager.session if manager else None
                mcp_loop   = manager.loop if manager else None

                if mcp_session and mcp_loop:
                    weather_provider = MCPWeatherProvider(mcp_client=mcp_session)
                    future = asyncio.run_coroutine_threadsafe(
                        evaluate_hive_state(
                            telemetry_data,
                            weather_provider=weather_provider,
                            memory=st.session_state.sentinel_memory,
                            demo_mode=st.session_state.get("demo_mode", False),
                        ),
                        mcp_loop,
                    )
                    return await asyncio.wrap_future(future)
                else:
                    logger.warning("MCP session unavailable. Running local fallback.")
                    return await evaluate_hive_state(
                        telemetry_data,
                        weather_provider=MCPWeatherProvider(mcp_client=None),
                        memory=st.session_state.sentinel_memory,
                        demo_mode=st.session_state.get("demo_mode", False),
                    )

            try:
                result = asyncio.run(run_evaluation())
                pubsub_msg_id = None
                st.session_state.pubsub_warning = None
                if result.get("severity") != "INFO":
                    st.write("Dispatching Pub/Sub Alert...")
                    try:
                        from agent.skills.pubsub_alerter import publish_alert
                        pubsub_msg_id = publish_alert(
                            state=result["state"],
                            action=result["action"],
                            severity=result["severity"],
                        )
                        st.write(f"Pub/Sub Alert Dispatched (Message ID: {pubsub_msg_id})")
                    except Exception as pubsub_err:
                        st.session_state.pubsub_warning = f"System Warning: Failed to dispatch Pub/Sub alert: {pubsub_err}"
                        logger.warning(f"Pub/Sub dispatch failed: {pubsub_err}")
                else:
                    st.write("No anomaly detected. Alert dispatch skipped.")

                # Persist evaluation event to SQLite database
                from frontend.database import log_diagnostic_event
                log_diagnostic_event(
                    hive_id=fleet_hive_id,
                    evaluation_result=result,
                    message_id=pubsub_msg_id,
                    telemetry_data=telemetry_data
                )

                st.session_state["evaluation_result"] = result
                st.session_state["evaluation_success"] = True

                # Update event history
                if "history" not in st.session_state:
                    st.session_state.history = []
                new_entry = {"state": result["state"], "action": result["action"]}
                if not st.session_state.history or st.session_state.history[-1] != new_entry:
                    st.session_state.history.append(new_entry)

                status.update(label="Diagnostic Complete!", state="complete")
            except Exception as e:
                st.write(f"Error executing flow: {e}")
                result = {"state": "ERROR_STATE", "action": f"Error: {e}", "severity": "CRITICAL"}
                st.session_state["evaluation_result"] = result
                st.session_state["evaluation_success"] = False
                status.update(label="Diagnostic Failed!", state="error")

    # Conditionally render diagnostic outputs if evaluation has run
    if st.session_state.get("evaluation_result") is not None:
        result = st.session_state["evaluation_result"]
        evaluation_success = st.session_state.get("evaluation_success", True)

        st.markdown("### ⚙️ Diagnostic Flow")
        flow_cols = st.columns(4)
        flow_cols[0].success("📥 Input Capture")
        flow_cols[1].success("🔌 MCP Context Fetch")
        if evaluation_success:
            flow_cols[2].success("🧠 Agent Reasoning")
            flow_cols[3].success("✉️ Alert Dispatch")
        else:
            flow_cols[2].error("🧠 Agent Reasoning")
            flow_cols[3].warning("✉️ Alert Dispatch")

        st.markdown("### 🎯 Agent Diagnostic Result")
        st.metric("Detected State", result["state"])

        conf_val = result.get("confidence")
        conf_str = f"{conf_val:.2%}" if isinstance(conf_val, (float, int)) else "N/A"

        try:
            schema_path = Path(project_root) / "simulated_data" / "telemetry_schema.json"
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            state_def = schema.get("state_definitions", {}).get(result["state"], {})
            thresh_val = state_def.get("confidence_override")
            if thresh_val is None:
                thresh_val = schema.get("event_resolution", {}).get("min_confidence_threshold", 0.75)
            thresh_str = f"{thresh_val:.2%}" if isinstance(thresh_val, (float, int)) else str(thresh_val)
        except Exception:
            thresh_str = "75.00% (Default)"

        st.markdown(
            f"<p style='font-size:0.9rem; color:#94a3b8; margin-top:-10px; margin-bottom:15px;'>"
            f"⚡ <strong>Confidence Score:</strong> {conf_str} &nbsp;|&nbsp; "
            f"🎯 <strong>Active Threshold:</strong> {thresh_str}"
            f"</p>",
            unsafe_allow_html=True
        )



        if result["severity"] != "INFO":
            st.error(f"Action Required: {result['action']}")
            if st.session_state.get("pubsub_warning"):
                st.warning(st.session_state.pubsub_warning)
        else:
            st.success(f"Action: {result['action']}")

        if "explanation" in result:
            st.info(f"🧠 **Agent Sentinel Explanation**:\n\n{result['explanation']}")

        # Check if the evaluated state is INITIALIZING_MONITORING or NORMAL_HEALTHY to show dynamic reason
        if result["state"] in ("INITIALIZING_MONITORING", "NORMAL_HEALTHY"):
            reason_text = result.get("reason") or result.get("explanation", "Operating within normal parameters.")
            st.info(f"💡 **Beekeeper Note:** {reason_text}")



        if result["state"] in STATE_DETAILS:
            details = STATE_DETAILS[result["state"]]
            with st.expander("ℹ️ Learn More: Why this state occurred & what to do", expanded=True):
                st.markdown(f"#### {details['title']}")
                st.info(f"**Why it occurred:** {details['why']}")

                try:
                    past_obs = st.session_state.sentinel_memory.get_context().get("past_observations", [])
                    if len(past_obs) > 1:
                        prev_obs = past_obs[-2]
                        st.warning(
                            f"⏱️ **Sentinel Memory Past Comparison:**  \n"
                            f"• Previous Detected State: `{prev_obs.get('state')}`  \n"
                            f"• Past Event Summary: *{prev_obs.get('explanation')}*"
                        )
                    else:
                        st.info("⏱️ **Sentinel Memory Past Comparison:** No prior observations recorded in this session yet.")
                except Exception as e:
                    logger.warning(f"Failed to load past comparison from memory: {e}")

                st.markdown("**Beekeeper Action Guide:**")
                for step in details["action_steps"]:
                    st.markdown(f"- {step}")

        # Spatial compliance check removed from Node Triage
        pass

        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("🙋‍♂️ Human-in-the-Loop: Review Agent Decision", expanded=True):
            st.markdown("Did the agent diagnose this correctly?")
            rating = st.slider("Accuracy Rating", 1, 5, 5, key="hitl_rating")
            comment = st.text_input("Beekeeper Notes", key="hitl_comment")
            if st.button("Submit Feedback"):
                try:
                    from frontend.database import (
                        get_feedback_confidence_overrides,
                        log_feedback,
                    )
                    hive_id = st.session_state.get("loaded_hive_id", "unknown")
                    evaluated_state = result.get("state", "")
                    log_feedback(
                        hive_id=hive_id,
                        evaluated_state=evaluated_state,
                        rating=rating,
                        comment=comment,
                    )
                    # Recompute confidence overrides and write to telemetry_schema.json
                    overrides = get_feedback_confidence_overrides()
                    if overrides and evaluated_state in overrides:
                        import json as _json
                        schema_path = Path(project_root) / "simulated_data" / "telemetry_schema.json"
                        try:
                            schema = _json.loads(schema_path.read_text(encoding="utf-8"))
                            for state_name, new_threshold in overrides.items():
                                if state_name in schema.get("state_definitions", {}):
                                    schema["state_definitions"][state_name]["confidence_override"] = new_threshold
                            schema_path.write_text(_json.dumps(schema, indent=4), encoding="utf-8")
                        except Exception as schema_err:
                            logger.warning(f"Could not update telemetry schema overrides: {schema_err}")

                    st.success(
                        f"✅ Feedback logged for **{evaluated_state}** "
                        f"(rating {rating}/5). "
                        "Confidence thresholds will update once ≥ 3 reviews are collected."
                    )
                except Exception as fb_err:
                    logger.error(f"Failed to persist feedback: {fb_err}")
                    st.error(f"Feedback could not be saved: {fb_err}")

    else:
        st.info("Adjust sliders or change profile and click 'Evaluate Hive State'.")

with col2:
    st.markdown("### 📜 Event Log")
    if st.session_state.get("history"):
        for entry in reversed(st.session_state.history):
            st.text(f"• {entry['state']}: {entry['action']}")
    else:
        st.info("No events triggered yet.")
