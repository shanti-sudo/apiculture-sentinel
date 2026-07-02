import datetime
import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent.skills.state_evaluator import evaluate_hive_state
from agent.skills.weather_provider import MCPWeatherProvider
from frontend.database import (
    get_feedback_confidence_overrides,
    log_feedback,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Apiculture Sentinel API", version="1.0.0")

_DB_PATH = Path(__file__).parent / "simulated_data" / "fleet.db"
_SCHEMA_PATH = Path(__file__).parent / "simulated_data" / "telemetry_schema.json"


# ── Shared Helpers ─────────────────────────────────────────────────────────────

@contextmanager
def _get_db():
    """Context manager for SQLite connection with auto-close."""
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        yield conn
    finally:
        conn.close()


def _build_eval_payload(payload: "TelemetryPayload") -> dict:
    """Constructs the structured evaluation input from a telemetry payload."""
    return {
        "edge_acoustic_classification": payload.edge_acoustic_classification,
        "acoustic_metrics": {
            "edge_acoustic_classification": payload.edge_acoustic_classification
        },
        "environmental_metrics": {
            "internal_temp_c": payload.internal_temp_c,
            "external_temp_c": payload.external_temp_c
        },
        "weight_metrics": {
            "hive_weight_kg": payload.hive_weight_kg
        }
    }


def _upsert_hive_fleet(conn: sqlite3.Connection, payload: "TelemetryPayload",
                       state: str, severity: str, action: str, ts: str) -> None:
    """Inserts or replaces a hive record in hive_fleet."""
    conn.execute("""
        INSERT OR REPLACE INTO hive_fleet
        (hive_id, site, state, severity, action,
         internal_temp_c, external_temp_c, edge_acoustic_classification,
         hive_weight_kg, weight_delta_1h, last_eval_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payload.hive_id, payload.site, state, severity, action,
        payload.internal_temp_c, payload.external_temp_c,
        payload.edge_acoustic_classification, payload.hive_weight_kg,
        payload.weight_delta_1h, ts
    ))


# ── Pydantic Models ────────────────────────────────────────────────────────────

class TelemetryPayload(BaseModel):
    hive_id: str = Field(..., json_schema_extra={"example": "H-00100"})
    site: str = Field(..., json_schema_extra={"example": "North_Field"})
    internal_temp_c: float = Field(..., json_schema_extra={"example": 34.5})
    external_temp_c: float = Field(..., json_schema_extra={"example": 22.0})
    edge_acoustic_classification: str = Field(..., json_schema_extra={"example": "STEADY_HUM"})
    hive_weight_kg: float = Field(..., json_schema_extra={"example": 42.1})
    weight_delta_1h: float = Field(0.0, json_schema_extra={"example": 0.2})


class FeedbackPayload(BaseModel):
    rating: int
    comment: str
    hive_id: str = ""
    evaluated_state: str = ""


# ── Background Task ────────────────────────────────────────────────────────────

async def run_async_evaluation(payload: TelemetryPayload):
    """Asynchronously runs state evaluation, publishes alerts, and updates database."""
    try:
        eval_payload = _build_eval_payload(payload)

        result = await evaluate_hive_state(
            eval_payload,
            weather_provider=MCPWeatherProvider(mcp_client=None),
            memory=None,
            demo_mode=True  # Force evaluation without memory constraints
        )

        state = result.get("state", "NORMAL_HEALTHY")
        severity = result.get("severity", "INFO")
        action = result.get("action", "Log normal status")

        # Publish alert if anomalous
        if severity != "INFO":
            try:
                from agent.skills.pubsub_alerter import publish_alert
                publish_alert(state=state, action=action, severity=severity)
            except Exception as e:
                logger.warning(f"Pub/Sub publishing failed gracefully: {e}")

        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with _get_db() as conn:
            with conn:
                _upsert_hive_fleet(conn, payload, state, severity, action, ts)

    except Exception as e:
        logger.error(f"Error during async evaluation of hive {payload.hive_id}: {e}")


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.post("/api/v1/telemetry/ingest")
async def ingest_telemetry(payload: TelemetryPayload, background_tasks: BackgroundTasks):
    """Accepts telemetry from IoT hives, writes initial status, and triggers async evaluation."""
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        with _get_db() as conn:
            with conn:
                _upsert_hive_fleet(conn, payload, "NORMAL_HEALTHY", "INFO", "Log normal status", ts)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database write failed: {e}")

    background_tasks.add_task(run_async_evaluation, payload)
    return {"status": "success", "message": f"Telemetry queued for evaluation on {payload.hive_id}"}


@app.post("/api/v1/feedback")
async def collect_feedback_v1(payload: FeedbackPayload):
    """Accepts beekeeper HITL feedback, persists it, and recomputes per-state confidence threshold."""
    logger.info(f"Feedback received: rating={payload.rating}, comment={payload.comment}, "
                f"hive={payload.hive_id}, state={payload.evaluated_state}")

    # 1. Persist to feedback_log table
    if payload.evaluated_state:
        try:
            log_feedback(
                hive_id=payload.hive_id,
                evaluated_state=payload.evaluated_state,
                rating=payload.rating,
                comment=payload.comment,
            )
        except Exception as e:
            logger.error(f"Failed to persist feedback: {e}")

    # 2. Recompute confidence overrides for all states with enough data
    if payload.evaluated_state:
        try:
            overrides = get_feedback_confidence_overrides()
            if overrides:
                schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
                for state_name, new_threshold in overrides.items():
                    if state_name in schema["state_definitions"]:
                        schema["state_definitions"][state_name]["confidence_override"] = new_threshold
                        logger.info(f"Updated confidence_override for {state_name}: {new_threshold}")
                _SCHEMA_PATH.write_text(json.dumps(schema, indent=4), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to update telemetry schema thresholds: {e}")

    return {
        "status": "success",
        "message": "Feedback logged successfully",
        "state": payload.evaluated_state or "unknown",
        "rating": payload.rating,
    }


@app.post("/api/v1/run")
async def run_evaluation_flat(payload: TelemetryPayload):
    """Synchronously runs state evaluation and returns the final decision as flat JSON."""
    eval_payload = _build_eval_payload(payload)

    result = await evaluate_hive_state(
        eval_payload,
        weather_provider=MCPWeatherProvider(mcp_client=None),
        memory=None,
        demo_mode=True
    )

    state = result.get("state", "NORMAL_HEALTHY")
    severity = result.get("severity", "INFO")
    action = result.get("action", "Log normal status")
    ts = datetime.datetime.now().isoformat(timespec="seconds")

    try:
        with _get_db() as conn:
            with conn:
                _upsert_hive_fleet(conn, payload, state, severity, action, ts)
                # Also log diagnostic event
                conn.execute("""
                    INSERT INTO diagnostic_events
                    (hive_id, timestamp, evaluated_state, severity, confidence_score, pubsub_message_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (payload.hive_id, ts, state, severity, 1.0, "direct-run-msg"))
    except Exception as e:
        logger.error(f"Failed to update database on direct run: {e}")

    return result
