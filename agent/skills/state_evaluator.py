"""
Agent Skill: Telemetry State Evaluator
Purpose: Reusable module to analyze JSON telemetry data (Acoustics + Environment)
and determine the hive's current health state by querying a local MCP weather server.

Design: This acts as the "brain" of the agent. It dynamically queries the MCP weather
server to fetch the current simulated weather, merges it with acoustic data, and outputs
a categorized state, action, and severity.
"""

import datetime
import json
import logging
import typing
from pathlib import Path

# Setup module-level logger
logger = logging.getLogger(__name__)

def find_value_in_dict(d: typing.Any, target_key: str) -> typing.Any:
    """Recursively searches for a key in a nested dictionary, using key aliases where needed."""
    if not isinstance(d, dict):
        return None

    if target_key in d:
        return d[target_key]

    mapping_aliases = {
        "frequency_hz": ["dominant_frequency_hz", "freq", "frequency_hz"],
        "acoustic_pattern": ["pitch_profile", "acoustic_pattern"],
    }

    aliases = mapping_aliases.get(target_key, [])
    for alias in aliases:
        if alias in d:
            return d[alias]

    for k, v in d.items():
        if isinstance(v, dict):
            res = find_value_in_dict(v, target_key)
            if res is not None:
                return res
    return None

def values_match(expected: typing.Any, actual: typing.Any) -> bool:
    """Compares expected and actual telemetry values, supporting domain concept aliases."""
    expected_str = str(expected).strip().lower()
    actual_str = str(actual).strip().lower()
    if expected_str == actual_str:
        return True

    aliases = {
        "colony_biosecurity_alert": ["erratic_spikes", "colony_biosecurity_alert"],
    }

    if expected_str in aliases:
        return actual_str in aliases[expected_str]

    return False

def validate_signal(signal_def: dict, val: typing.Any) -> bool:
    """Checks if a telemetry signal value complies with range or match requirements."""
    if val is None:
        return False

    sig_type = signal_def.get("type")
    expected_value = signal_def.get("value")

    if sig_type == "range":
        if not isinstance(expected_value, list) or len(expected_value) != 2:
            return False
        min_val, max_val = expected_value
        try:
            val_float = float(val)
            if min_val is not None and val_float < min_val:
                return False
            if max_val is not None and val_float > max_val:
                return False
            return True
        except (ValueError, TypeError):
            return False

    elif sig_type == "match":
        return values_match(expected_value, val)

    return False

def validate_persistence(
    state_name: str,
    persistence_hours: int,
    required_signals: list,
    memory_context: dict,
    telemetry_data: dict
) -> bool:
    """Validates the persistence of signal conditions using history from SentinelMemory."""
    if persistence_hours <= 0:
        return True

    past_obs = memory_context.get("past_observations", [])
    if not past_obs:
        return True

    current_time = datetime.datetime.now()
    window_start = current_time - datetime.timedelta(hours=persistence_hours)

    relevant_obs = []
    for obs in past_obs:
        try:
            obs_time = datetime.datetime.fromisoformat(obs["timestamp"])
            if obs_time >= window_start:
                relevant_obs.append(obs)
        except Exception:
            relevant_obs.append(obs)

    if not relevant_obs:
        return True

    for obs in relevant_obs:
        obs_telemetry = obs.get("telemetry")
        if not obs_telemetry:
            if obs.get("state") != state_name:
                return False
            continue

        for sig in required_signals:
            val = find_value_in_dict(obs_telemetry, sig["id"])
            if not validate_signal(sig, val):
                return False

    return True

def get_last_hive_feedback(hive_id: str) -> int | None:
    try:
        db_path = Path(__file__).resolve().parent.parent.parent / "simulated_data" / "fleet.db"
        if not db_path.exists():
            return None
        import sqlite3
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT rating FROM feedback_log WHERE hive_id = ? ORDER BY timestamp DESC, id DESC LIMIT 1",
                (hive_id,)
            ).fetchone()
            if row:
                return row["rating"]
    except Exception as e:
        logger.warning(f"Failed to query last feedback for hive {hive_id}: {e}")
    return None

async def evaluate_hive_state(
    telemetry_data: dict,
    weather_provider: typing.Any | None = None,
    memory: typing.Any = None,
    demo_mode: bool = False
) -> dict:
    """
    Evaluates acoustic and environmental metrics to determine hive health by dynamically
    parsing standard signal requirements from telemetry_schema.json.
    
    Args:
        telemetry_data (dict): JSON telemetry payload.
        weather_provider (typing.Any, optional): Provider for current simulated weather.
        memory (typing.Any, optional): SentinelMemory object for past observations.
        
    Returns:
        dict: Evaluation results containing 'state', 'action', 'severity', and 'explanation'.
    """
    try:
        if telemetry_data is None:
            raise ValueError("Telemetry data payload cannot be None")

        acoustics = telemetry_data.get("acoustic_metrics", {})
        environment = telemetry_data.get("environmental_metrics", {})
        raw_delta = telemetry_data.get("weight_metrics", {}).get("weight_delta_1h")

        # Retrieve memory context for Sentinel-based reasoning
        memory_context = memory.get_context() if memory is not None else {
            "historical_patterns": {
                "weight_trend": "This hive normally increases weight every April",
                "heat_stress_trend": "This location has heat stress every afternoon"
            },
            "past_observations": []
        }
        patterns = memory_context.get("historical_patterns", {})

        # Initialize weather provider if not supplied
        if weather_provider is None:
            from agent.skills.weather_provider import MCPWeatherProvider
            weather_provider = MCPWeatherProvider()

        # Query weather provider to fetch external environmental context
        mcp_weather = await weather_provider.get_weather_context()

        # Extract metrics with safe defaults for explanations
        edge_acoustic_classification = find_value_in_dict(telemetry_data, "edge_acoustic_classification") or "STEADY_HUM"

        # Decouple: internal temp belongs strictly to local hive telemetry
        int_temp = environment.get("internal_temp_c", 35.0)
        # External temp belongs strictly to MCP weather context (with fallback to payload)
        ext_temp = mcp_weather.get("external_temp_c", environment.get("external_temp_c", 20.0))
        weight = telemetry_data.get("weight_metrics", {}).get("hive_weight_kg", 40.0)

        # Calculate weight_delta_1h based on most recent historical weight in SentinelMemory
        historical_weight = None
        past_obs = memory_context.get("past_observations", [])
        for obs in reversed(past_obs):
            obs_telemetry = obs.get("telemetry")
            if obs_telemetry:
                w = find_value_in_dict(obs_telemetry, "hive_weight_kg")
                if w is not None:
                    historical_weight = float(w)
                    break

        if historical_weight is not None:
            weight_delta_1h = float(weight) - historical_weight
        else:
            weight_delta_1h = 0.0

        if "weight_metrics" not in telemetry_data:
            telemetry_data["weight_metrics"] = {}
        telemetry_data["weight_metrics"]["weight_delta_1h"] = weight_delta_1h

        # Determine if we have >6 hours of history
        has_six_hours_history = False
        if past_obs:
            try:
                oldest_time = None
                for obs in past_obs:
                    if "timestamp" in obs:
                        t = datetime.datetime.fromisoformat(obs["timestamp"])
                        if oldest_time is None or t < oldest_time:
                            oldest_time = t
                if oldest_time is not None:
                    time_diff = datetime.datetime.now() - oldest_time
                    if time_diff.total_seconds() > 6 * 3600:
                        has_six_hours_history = True
            except Exception as e:
                logger.warning(f"Error calculating history length: {e}")

        # Spatial validation has been decoupled from the real-time node triage flow
        spatial_report = None

        # Fallback local schema definition matching simulated_data/telemetry_schema.json
        fallback_schema = {
            "state_definitions": {
                "CATASTROPHIC_MASS_LOSS": {
                    "required_signals": [
                        {"id": "weight_delta_1h", "type": "range", "value": [-100.0, -5.1]}
                    ],
                    "supporting_signals": [
                        {"id": "edge_acoustic_classification", "type": "match", "value": "ERRATIC_MITE_STRESS"}
                    ],
                    "persistence_requirement": 0,
                    "severity": "CRITICAL",
                    "description": "Massive, non-biological weight loss indicating theft, predator interference, or hardware failure. Immediate inspection required."
                },
                "SWARM_DEPARTURE_DETECTED": {
                    "required_signals": [
                        {"id": "weight_delta_1h", "type": "range", "value": [-5.0, -1.5]},
                        {"id": "edge_acoustic_classification", "type": "match", "value": "QUIESCENT"}
                    ],
                    "persistence_requirement": 6,
                    "severity": "CRITICAL"
                },
                "PRE_SWARMING_ALERT": {
                    "required_signals": [
                        {"id": "edge_acoustic_classification", "type": "match", "value": "PIPING_DETECTED"}
                    ],
                    "supporting_signals": [
                        {"id": "weight_trend", "type": "match", "value": "decreasing"}
                    ],
                    "persistence_requirement": 4,
                    "severity": "HIGH"
                },
                "QUEENLESS_COLONY": {
                    "required_signals": [
                        {"id": "edge_acoustic_classification", "type": "match", "value": "MOURNING_ROAR"}
                    ],
                    "supporting_signals": [
                        {"id": "internal_temp_c", "type": "range", "value": [33, 35]}
                    ],
                    "persistence_requirement": 12,
                    "severity": "CRITICAL"
                },
                "COLD_STRESS_ALERT": {
                    "required_signals": [
                        {"id": "internal_temp_c", "type": "range", "value": [20, 31.9]}
                    ],
                    "persistence_requirement": 2,
                    "severity": "HIGH"
                },
                "PEST_DISTRESS_VARROA": {
                    "required_signals": [
                        {"id": "edge_acoustic_classification", "type": "match", "value": "ERRATIC_MITE_STRESS"},
                        {"id": "internal_temp_c", "type": "range", "value": [33, 35.5]}
                    ],
                    "persistence_requirement": 24,
                    "severity": "MEDIUM"
                },
                "HEAT_STRESS_ALERT": {
                    "required_signals": [
                        {"id": "internal_temp_c", "type": "range", "value": [37, 39.9]}
                    ],
                    "persistence_requirement": 2,
                    "severity": "HIGH"
                },
                "CRITICAL_HEAT_ALERT": {
                    "required_signals": [
                        {"id": "internal_temp_c", "type": "range", "value": [40, 50]}
                    ],
                    "persistence_requirement": 1,
                    "severity": "CRITICAL"
                },
                "NORMAL_HEALTHY": {
                    "required_signals": [
                        {"id": "internal_temp_c", "type": "range", "value": [32, 36]},
                        {"id": "edge_acoustic_classification", "type": "match", "value": "STEADY_HUM"}
                    ],
                    "persistence_requirement": 0,
                    "severity": "LOW"
                }
            }
        }

        # Dynamically load the telemetry schema
        schema_path = Path(__file__).resolve().parent.parent.parent / "simulated_data" / "telemetry_schema.json"
        schema = fallback_schema
        try:
            if schema_path.exists():
                with open(schema_path, encoding="utf-8") as f:
                    schema = json.load(f)
        except Exception as err:
            logger.warning(f"Error loading telemetry schema from {schema_path}: {err}. Using fallback.")

        # Extract hive_id
        hive_id = telemetry_data.get("hive_id") or telemetry_data.get("hive_metadata", {}).get("hive_id", "unknown")

        # Determine first-run status (empty history / no baseline weight)
        is_first_run = len(past_obs) == 0

        # Check raw telemetry weight delta
        check_delta = raw_delta if raw_delta is not None else weight_delta_1h
        is_extreme_delta = False
        if check_delta is not None:
            if check_delta <= -5.0 or abs(check_delta) > 5.0:
                is_extreme_delta = True

        # Reconcile diagnostic states
        candidates = []
        SEVERITY_PRIORITY = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}

        state_defs = schema.get("state_definitions", {})
        event_res = schema.get("event_resolution", {})
        min_threshold = event_res.get("min_confidence_threshold", 0.75)
        req_matching = event_res.get("required_signal_matching", True)

        state_confidences = {}
        for state_name, state_def in state_defs.items():
            required_signals = state_def.get("required_signals", [])
            supporting_signals = state_def.get("supporting_signals", [])

            total_req = len(required_signals)
            total_supp = len(supporting_signals)

            matched_req = 0
            for sig in required_signals:
                val = find_value_in_dict(telemetry_data, sig["id"])
                if validate_signal(sig, val):
                    matched_req += 1

            matched_supp = 0
            for sig in supporting_signals:
                val = find_value_in_dict(telemetry_data, sig["id"])
                if validate_signal(sig, val):
                    matched_supp += 1

            if req_matching and matched_req < total_req:
                confidence = 0.0
            else:
                if total_req > 0 and total_supp > 0:
                    confidence = (matched_req / total_req) * 0.75 + (matched_supp / total_supp) * 0.25
                elif total_req > 0:
                    confidence = matched_req / total_req
                elif total_supp > 0:
                    confidence = matched_supp / total_supp
                else:
                    confidence = 1.0

            state_confidences[state_name] = confidence

            # Use per-state confidence_override if set by the HITL feedback loop,
            # otherwise fall back to the global min_threshold.
            state_threshold = state_def.get("confidence_override") or min_threshold

            if confidence >= state_threshold:
                persistence_requirement = state_def.get("persistence_requirement", 0)
                if demo_mode or validate_persistence(state_name, persistence_requirement, required_signals, memory_context, telemetry_data):
                    candidates.append((state_name, state_def, confidence))

        if candidates:
            # Sort by severity priority (descending)
            candidates.sort(key=lambda x: (SEVERITY_PRIORITY.get(x[1].get("severity", "INFO"), 0), x[2]), reverse=True)
            base_state, state_def, selected_confidence = candidates[0]
            severity = state_def.get("severity", "INFO")
        else:
            base_state = "NORMAL_HEALTHY"
            state_def = state_defs.get("NORMAL_HEALTHY", {})
            severity = "INFO"
            selected_confidence = state_confidences.get("NORMAL_HEALTHY", 1.0)

        # If the evaluated state is NORMAL_HEALTHY but the previous state in memory was INITIALIZING_MONITORING,
        # remain in INITIALIZING_MONITORING (building history) rather than instantly reverting.
        if base_state == "NORMAL_HEALTHY":
            previous_state = past_obs[-1].get("state") if past_obs else None
            if previous_state == "INITIALIZING_MONITORING" and not has_six_hours_history:
                base_state = "INITIALIZING_MONITORING"
                state_def = {}
                severity = "INFO"
                selected_confidence = 0.5

        # Solar Loading check: compare telemetry's internal_temp (int_temp) against the MCP's
        # external weather context to detect CRITICAL_HEAT_EXPOSURE.
        if base_state == "CRITICAL_HEAT_ALERT":
            mcp_ext_temp = float(mcp_weather.get("external_temp_c", 20.0))
            mcp_conditions = mcp_weather.get("conditions", "Sunny")
            if mcp_conditions == "Sunny" and mcp_ext_temp >= 30.0:
                logger.info("CRITICAL_HEAT_EXPOSURE detected: Solar loading active (Sunny & external temp >= 30.0C)")
            else:
                logger.info("Downgrading CRITICAL_HEAT_ALERT to HEAT_STRESS_ALERT: No solar loading (weather not Sunny or external temp < 30.0C)")
                base_state = "HEAT_STRESS_ALERT"
                state_def = state_defs.get("HEAT_STRESS_ALERT", {})
                severity = "HIGH"

        # Check if an anomalous state was matched by signals but failed persistence
        persistence_failed_state = None
        persistence_failed_hours = 0
        if not demo_mode:
            for s_name, s_def in state_defs.items():
                if s_name == "NORMAL_HEALTHY":
                    continue
                required_signals = s_def.get("required_signals", [])
                total_req = len(required_signals)
                matched_req = 0
                for sig in required_signals:
                    val = find_value_in_dict(telemetry_data, sig["id"])
                    if validate_signal(sig, val):
                        matched_req += 1
                if req_matching and matched_req < total_req:
                    s_confidence = 0.0
                else:
                    supporting_signals = s_def.get("supporting_signals", [])
                    total_supp = len(supporting_signals)
                    matched_supp = 0
                    for sig in supporting_signals:
                        val = find_value_in_dict(telemetry_data, sig["id"])
                        if validate_signal(sig, val):
                            matched_supp += 1
                    if total_req > 0 and total_supp > 0:
                        s_confidence = (matched_req / total_req) * 0.75 + (matched_supp / total_supp) * 0.25
                    elif total_req > 0:
                        s_confidence = matched_req / total_req
                    elif total_supp > 0:
                        s_confidence = matched_supp / total_supp
                    else:
                        s_confidence = 1.0
                if s_confidence >= (s_def.get("confidence_override") or min_threshold):
                    p_req = s_def.get("persistence_requirement", 0)
                    if not validate_persistence(s_name, p_req, required_signals, memory_context, telemetry_data):
                        persistence_failed_state = s_name
                        persistence_failed_hours = p_req
                        break

        # First-Run Calibration and Extreme Telemetry Overrides
        if is_first_run:
            if is_extreme_delta:
                base_state = "CATASTROPHIC_MASS_LOSS"
                state_def = state_defs.get("CATASTROPHIC_MASS_LOSS", {})
                severity = "CRITICAL"
                action = "Trigger Emergency Apiary Investigation"
                selected_confidence = 0.5
            else:
                base_state = "INITIALIZING_MONITORING"
                state_def = {}
                severity = "INFO"
                action = "Establish baseline monitoring"
                selected_confidence = 0.5

        if base_state == "NORMAL_HEALTHY":
            action = "Log normal status"
            severity = "INFO"
        elif base_state == "INITIALIZING_MONITORING":
            action = "Establish baseline monitoring"
            severity = "INFO"
        else:
            STATE_ACTIONS = {
                "CATASTROPHIC_MASS_LOSS": "Trigger Emergency Apiary Investigation",
                "SWARM_DEPARTURE_DETECTED": "Dispatch Swarm Recovery Protocol",
                "PRE_SWARMING_ALERT": "Trigger Space Inspection Alert",
                "QUEENLESS_COLONY": "Trigger Queen Replacement Alert",
                "COLD_STRESS_ALERT": "Publish Thermal Blanket Request",
                "PEST_DISTRESS_VARROA": "Trigger Pest Inspection Alert",
                "HEAT_STRESS_ALERT": "Trigger Hive Ventilation Alert",
                "CRITICAL_HEAT_ALERT": "Trigger Critical Cooling Request"
            }
            action = STATE_ACTIONS.get(base_state, "Action unknown")
            severity = state_def.get("severity", "INFO") if state_def else "INFO"

        # Agentic Reasoning: Compare telemetry vs memory patterns for severity upgrades
        repeated_count = sum(1 for obs in past_obs if obs.get("state") == base_state)
        if repeated_count > 0:
            logger.info(f"SentinelMemory: Detected repeated state {base_state} ({repeated_count} times). Upgrading severity.")
            if severity == "HIGH":
                severity = "CRITICAL"
            elif severity == "MEDIUM":
                severity = "HIGH"
            elif severity in ("LOW", "INFO"):
                severity = "HIGH"

        # Formulate synthesized explanation
        weight_trend = patterns.get("weight_trend", "This hive normally increases weight every April")

        # Build structured trace fields
        obs_line = f"Internal Temp = {int_temp:.1f}°C, Weight = {weight:.1f}kg (Delta 1h = {weight_delta_1h:.1f}kg), Acoustics = '{edge_acoustic_classification}'"
        mem_line = f"Historical pattern: '{weight_trend}'. Past history length = {len(past_obs)} entries."
        ctx_line = f"External Weather: {mcp_weather.get('conditions', 'Sunny')} ({ext_temp:.1f}°C), Wind: {mcp_weather.get('wind_speed_kmh', 10.0)} km/h."

        if base_state == "INITIALIZING_MONITORING":
            reasoning_str = "Insufficient temporal data; establishing baseline."
        elif base_state == "CATASTROPHIC_MASS_LOSS":
            if is_first_run and is_extreme_delta:
                reasoning_str = "High-magnitude event detected; immediate attention required despite limited history."
            else:
                reasoning_str = f"A massive, non-biological weight drop of {weight_delta_1h:.1f}kg was detected, which is highly abnormal and indicates potential theft, predator intrusion, or hardware scale malfunction."
        elif base_state == "SWARM_DEPARTURE_DETECTED":
            reasoning_str = f"A sudden weight drop of {weight_delta_1h:.1f}kg combined with a quiet acoustic profile ('{edge_acoustic_classification}') indicates that a large portion of the hive has swarmed out."
        elif base_state == "COLD_STRESS_ALERT":
            reasoning_str = f"Internal temperature is {int_temp:.1f}°C, which has dropped below the critical brood nesting range of 32°C due to freezing external conditions ({ext_temp:.1f}°C)."
        elif base_state == "HEAT_STRESS_ALERT":
            reasoning_str = f"Internal temperature is elevated at {int_temp:.1f}°C, exceeding the normal 32°C-36°C brood regulation range and triggering fanning behaviors."
        elif base_state == "CRITICAL_HEAT_ALERT":
            reasoning_str = f"Internal temperature is dangerously high at {int_temp:.1f}°C (exceeding 40°C), which will cause rapid brood mortality and risk comb/wax melting."
        elif base_state in ("PRE_SWARMING_ALERT", "SWARM_PREPARATION"):
            reasoning_str = f"Edge AI acoustic sensor detected '{edge_acoustic_classification}' (queen piping), indicating imminent swarm departure."
        elif base_state == "QUEENLESS_COLONY":
            reasoning_str = f"Edge AI acoustic sensor detected '{edge_acoustic_classification}' (wailing roar), signaling queenlessness due to a lack of queen mandibular pheromones."
        elif base_state == "PEST_DISTRESS_VARROA":
            reasoning_str = f"Edge AI acoustic classification is '{edge_acoustic_classification}', indicating severe Varroa mite parasitic distress."
        else:
            if persistence_failed_state:
                reasoning_str = f"Anomalous telemetry signal for '{persistence_failed_state}' was captured, but was filtered out because it failed the temporal persistence filter of {persistence_failed_hours} hours in Sentinel Memory."
            else:
                reasoning_str = f"All telemetry metrics are normal and stable. Internal temperature ({int_temp:.1f}°C) and weight ({weight:.1f}kg) align with expected baseline patterns."

        # Compile Sentinel Trace Output
        explanation = (
            f"🧠 **Sentinel Agent Trace:**\n"
            f"• **Observation**: {obs_line}\n"
            f"• **Memory Retrieval**: {mem_line}\n"
            f"• **Context (MCP)**: {ctx_line}\n"
            f"• **Reasoning**: {reasoning_str}\n"
            f"• **Decision**: `{base_state}`\n"
            f"• **Action**: {action}"
        )

        # Generate synthetic explanation for memory logging
        if base_state == "INITIALIZING_MONITORING":
            synthetic_explanation = "Initializing monitoring: establishing baseline."
        elif base_state == "CATASTROPHIC_MASS_LOSS":
            if is_first_run and is_extreme_delta:
                synthetic_explanation = "High-magnitude event detected; immediate attention required despite limited history."
            else:
                synthetic_explanation = f"Massive weight drop of {weight_delta_1h:.1f}kg suggests non-biological loss (theft, bear attack, or hardware failure)."
        elif base_state == "SWARM_DEPARTURE_DETECTED":
            synthetic_explanation = f"Weight delta is {weight_delta_1h:.1f}kg and Edge AI detected QUIESCENT, suggesting swarm departure."
        elif base_state == "QUEENLESS_COLONY":
            synthetic_explanation = "Edge AI acoustic classification is 'MOURNING_ROAR', indicating a wailing hum due to queenlessness."
        elif base_state == "PEST_DISTRESS_VARROA":
            synthetic_explanation = "Edge AI acoustic classification is 'ERRATIC_MITE_STRESS', suggesting pest distress."
        elif base_state == "COLD_STRESS_ALERT":
            synthetic_explanation = f"Internal temperature is {int_temp:.1f}°C (range: < 32.0°C), triggering cold stress warning."
        elif base_state == "HEAT_STRESS_ALERT":
            synthetic_explanation = f"Internal temperature is {int_temp:.1f}°C (range: 37.0-39.9°C), triggering heat stress warning."
        elif base_state == "CRITICAL_HEAT_ALERT":
            synthetic_explanation = f"Internal temperature is {int_temp:.1f}°C (range: >= 40.0°C), triggering critical heat warning."
        elif base_state in ("PRE_SWARMING_ALERT", "SWARM_PREPARATION"):
            synthetic_explanation = "Edge AI acoustic classification is 'PIPING_DETECTED', indicating swarm preparation."
        else:
            if persistence_failed_state:
                synthetic_explanation = (
                    f"Anomalous state '{persistence_failed_state}' was matched but failed the "
                    f"persistence requirement of {persistence_failed_hours} hours. Reverted to normal."
                )
            else:
                synthetic_explanation = f"Internal temperature is {int_temp:.1f}°C (range: >= 32.0°C) and Edge AI classification is 'STEADY_HUM', which is within normal parameters."

        # Confidence Scaling
        base_confidence = 0.5 if is_first_run else selected_confidence
        
        memory_multiplier = 0.2 if has_six_hours_history else 0.0

        feedback_bonus = 0.0
        if hive_id and hive_id != "unknown":
            last_rating = get_last_hive_feedback(hive_id)
            if last_rating is not None:
                if last_rating <= 2:
                    feedback_bonus = -0.2
                elif last_rating == 5:
                    feedback_bonus = 0.1

        final_confidence = base_confidence + memory_multiplier + feedback_bonus
        final_confidence = max(0.0, min(1.0, final_confidence))

        result = {
            "state": base_state,
            "action": action,
            "severity": severity,
            "explanation": explanation,
            "confidence": final_confidence,
            "reason": reasoning_str
        }

        if memory is not None:
            try:
                memory.add_observation(base_state, synthetic_explanation, telemetry=telemetry_data)
            except Exception as e:
                logger.error(f"Failed to add observation to memory: {e}")

        if demo_mode and base_state not in ("NORMAL_HEALTHY", "INITIALIZING_MONITORING"):
            result["explanation"] += "\n\n[DEMO MODE ACTIVE: Temporal persistence requirement bypassed for demonstration]"

        return result

    except Exception as e:
        logger.error(f"Critical error in evaluate_hive_state: {e}")
        return {
            "state": "ERROR",
            "action": f"Error: {e}",
            "severity": "CRITICAL",
            "explanation": f"An unexpected system failure occurred during hive evaluation: {e}"
        }

# ---------------------------------------------------------
# Local Testing / Mock Execution for Debugging
# ---------------------------------------------------------
if __name__ == "__main__":
    # Test Payload mimicking a Cold Stress scenario where the internal temp is low
    test_payload = {
        "edge_acoustic_classification": "STEADY_HUM",
        "acoustic_metrics": {
            "edge_acoustic_classification": "STEADY_HUM"
        },
        "environmental_metrics": {
            "internal_temp_c": 32.0,  # Below 33C
        }
    }

    # Configure logging for main runner
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (%(name)s) %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z'
    )
    # Run the evaluation async
    result = asyncio.run(evaluate_hive_state(test_payload))
    logger.info(f"Evaluated State: {result['state']} | context: {test_payload}")
    logger.info(f"Action: {result['action']}")
    logger.info(f"Severity: {result['severity']}")

