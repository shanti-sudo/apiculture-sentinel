"""
Fleet Simulation Persistence Layer
Manages a SQLite-backed fleet of 10,000 hives across 4 apiary sites.
"""

import datetime
import json
import logging
import random
import sqlite3
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent / "simulated_data" / "fleet.db"

SITES = ["North_Field", "West_Valley", "East_Ridge", "South_Grove"]
TOTAL_HIVES = 10_000

STATE_ACTIONS = {
    "CATASTROPHIC_MASS_LOSS": "Trigger Emergency Apiary Investigation",
    "SWARM_DEPARTURE_DETECTED": "Dispatch Swarm Recovery Protocol",
    "PRE_SWARMING_ALERT": "Trigger Space Inspection Alert",
    "QUEENLESS_COLONY": "Trigger Queen Replacement Alert",
    "COLD_STRESS_ALERT": "Publish Thermal Blanket Request",
    "PEST_DISTRESS_VARROA": "Trigger Pest Inspection Alert",
    "HEAT_STRESS_ALERT": "Trigger Hive Ventilation Alert",
    "CRITICAL_HEAT_ALERT": "Trigger Critical Cooling Request",
    "NORMAL_HEALTHY": "Log normal status",
}

SEVERITY_MAP = {
    "NORMAL_HEALTHY": "INFO",
    "HEAT_STRESS_ALERT": "HIGH",
    "COLD_STRESS_ALERT": "HIGH",
    "CRITICAL_HEAT_ALERT": "CRITICAL",
    "CATASTROPHIC_MASS_LOSS": "CRITICAL",
    "SWARM_DEPARTURE_DETECTED": "CRITICAL",
    "PRE_SWARMING_ALERT": "HIGH",
    "QUEENLESS_COLONY": "CRITICAL",
    "PEST_DISTRESS_VARROA": "MEDIUM",
}


@contextmanager
def _get_conn():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _create_schema():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hive_fleet (
                hive_id                      TEXT PRIMARY KEY,
                site                         TEXT NOT NULL,
                state                        TEXT NOT NULL,
                severity                     TEXT NOT NULL,
                action                       TEXT NOT NULL,
                internal_temp_c              REAL NOT NULL,
                external_temp_c              REAL NOT NULL,
                edge_acoustic_classification TEXT NOT NULL,
                hive_weight_kg               REAL NOT NULL,
                weight_delta_1h              REAL NOT NULL DEFAULT 0.0,
                last_eval_ts                 TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS diagnostic_events (
                hive_id           TEXT NOT NULL,
                timestamp         TEXT NOT NULL,
                evaluated_state   TEXT NOT NULL,
                severity          TEXT NOT NULL,
                confidence_score  REAL NOT NULL,
                pubsub_message_id TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback_log (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                hive_id        TEXT NOT NULL,
                evaluated_state TEXT NOT NULL,
                rating         INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                comment        TEXT,
                timestamp      TEXT NOT NULL
            )
        """)


def _hive_count() -> int:
    try:
        with _get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM hive_fleet").fetchone()[0]
    except Exception:
        return 0


# ── HITL Feedback Persistence ──────────────────────────────────────────────────

DEFAULT_CONFIDENCE = 0.75
_MIN_FEEDBACK_COUNT = 3  # Minimum ratings before a per-state override is applied

# Rating → confidence threshold mapping:
#   avg >= 4.0  → agent trusted    → lenient  (0.70)
#   avg 3.0–3.9 → agent acceptable → default  (0.75)
#   avg < 3.0   → agent unreliable → strict   (0.85)
_RATING_TO_THRESHOLD = [
    (4.0, 0.70),
    (3.0, 0.75),
    (0.0, 0.85),
]


def _rating_to_confidence(avg_rating: float) -> float:
    """Maps an average beekeeper rating (1–5) to a confidence threshold."""
    for min_rating, threshold in _RATING_TO_THRESHOLD:
        if avg_rating >= min_rating:
            return threshold
    return DEFAULT_CONFIDENCE


def log_feedback(hive_id: str, evaluated_state: str, rating: int, comment: str) -> None:
    """Persists a beekeeper HITL review to feedback_log."""
    _create_schema()
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO feedback_log (hive_id, evaluated_state, rating, comment, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (hive_id, evaluated_state, rating, comment, ts)
        )
    logger.info(f"Feedback logged: hive={hive_id} state={evaluated_state} rating={rating}")


def get_average_rating_by_state(evaluated_state: str) -> tuple[float | None, int]:
    """
    Returns (average_rating, count) for the given state.
    Returns (None, 0) if no feedback exists for this state.
    """
    try:
        _create_schema()
        with _get_conn() as conn:
            row = conn.execute(
                """
                SELECT AVG(rating) as avg_rating, COUNT(*) as count
                FROM feedback_log
                WHERE evaluated_state = ?
                """,
                (evaluated_state,)
            ).fetchone()
        if row and row["count"] > 0:
            return float(row["avg_rating"]), int(row["count"])
    except Exception as e:
        logger.warning(f"Failed to read feedback for state {evaluated_state}: {e}")
    return None, 0


def get_feedback_confidence_overrides() -> dict[str, float]:
    """
    Returns a dict mapping state_name → computed confidence threshold
    for all states that have >= _MIN_FEEDBACK_COUNT ratings.
    States with insufficient data are excluded (caller falls back to global default).
    """
    overrides: dict[str, float] = {}
    try:
        _create_schema()
        with _get_conn() as conn:
            rows = conn.execute(
                """
                SELECT evaluated_state, AVG(rating) as avg_rating, COUNT(*) as count
                FROM feedback_log
                GROUP BY evaluated_state
                HAVING COUNT(*) >= ?
                """,
                (_MIN_FEEDBACK_COUNT,)
            ).fetchall()
        for row in rows:
            overrides[row["evaluated_state"]] = _rating_to_confidence(float(row["avg_rating"]))
    except Exception as e:
        logger.warning(f"Failed to compute confidence overrides: {e}")
    return overrides


def seed_fleet_database(force: bool = False):
    """
    Seeds the fleet database with 10,000 hives if not already populated.
    Pass force=True to drop and re-seed deterministically.
    """
    _create_schema()
    if not force and _hive_count() >= TOTAL_HIVES:
        logger.info("Fleet database already seeded. Skipping.")
        return

    if force:
        with _get_conn() as conn:
            conn.execute("DELETE FROM hive_fleet")

    rng = random.Random(42)  # Deterministic seed for reproducibility
    now = datetime.datetime.now()

    # Pre-assign exactly 500 anomaly hive indices (5%) deterministically.
    # 200 CRITICAL_HEAT_ALERT + 200 CATASTROPHIC_MASS_LOSS + 100 SWARM_DEPARTURE_DETECTED
    all_indices = list(range(TOTAL_HIVES))
    rng.shuffle(all_indices)
    anomaly_assignments: dict = {}
    for idx in all_indices[:200]:
        anomaly_assignments[idx] = "CRITICAL_HEAT_ALERT"
    for idx in all_indices[200:400]:
        anomaly_assignments[idx] = "CATASTROPHIC_MASS_LOSS"
    for idx in all_indices[400:500]:
        anomaly_assignments[idx] = "SWARM_DEPARTURE_DETECTED"

    hives_per_site = TOTAL_HIVES // len(SITES)
    rows = []

    for site_idx, site in enumerate(SITES):
        for local_i in range(hives_per_site):
            global_i = site_idx * hives_per_site + local_i
            hive_id = f"H-{global_i + 1:05d}"
            ts = (now - datetime.timedelta(minutes=rng.randint(0, 240))).isoformat(timespec="seconds")

            state = anomaly_assignments.get(global_i, "NORMAL_HEALTHY")

            if state == "NORMAL_HEALTHY":
                internal_temp = rng.uniform(32.5, 35.8)
                external_temp = rng.uniform(15.0, 28.0)
                acoustic = "STEADY_HUM"
                weight = rng.uniform(35.0, 55.0)
                weight_delta = rng.uniform(-0.4, 0.4)
            elif state == "CRITICAL_HEAT_ALERT":
                internal_temp = rng.uniform(40.0, 44.5)
                external_temp = rng.uniform(30.0, 40.0)
                acoustic = "STEADY_HUM"
                weight = rng.uniform(35.0, 50.0)
                weight_delta = rng.uniform(-0.5, 0.5)
            elif state == "CATASTROPHIC_MASS_LOSS":
                internal_temp = rng.uniform(32.0, 36.0)
                external_temp = rng.uniform(15.0, 28.0)
                acoustic = "ERRATIC_MITE_STRESS"
                weight = rng.uniform(18.0, 28.0)
                weight_delta = rng.uniform(-14.0, -5.1)
            else:  # SWARM_DEPARTURE_DETECTED
                internal_temp = rng.uniform(32.0, 36.0)
                external_temp = rng.uniform(15.0, 28.0)
                acoustic = "QUIESCENT"
                weight = rng.uniform(30.0, 38.0)
                weight_delta = rng.uniform(-5.0, -1.5)

            severity = SEVERITY_MAP.get(state, "INFO")
            action = STATE_ACTIONS.get(state, "Log normal status")

            rows.append((
                hive_id, site, state, severity, action,
                round(internal_temp, 2), round(external_temp, 2),
                acoustic, round(weight, 2), round(weight_delta, 2), ts
            ))

    with _get_conn() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO hive_fleet
            (hive_id, site, state, severity, action,
             internal_temp_c, external_temp_c, edge_acoustic_classification,
             hive_weight_kg, weight_delta_1h, last_eval_ts)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)

    # Seed initial diagnostic_events for anomalous hives
    event_rows = []
    for r in rows:
        hive_id, site, state, severity, action, int_temp, ext_temp, acoustic, weight, weight_delta, ts = r
        if state != "NORMAL_HEALTHY":
            event_rows.append((hive_id, ts, state, severity, 1.0, f"mock-msg-{hive_id}"))

    with _get_conn() as conn:
        conn.execute("DELETE FROM diagnostic_events")
        conn.executemany("""
            INSERT INTO diagnostic_events
            (hive_id, timestamp, evaluated_state, severity, confidence_score, pubsub_message_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, event_rows)

    logger.info(f"Fleet database seeded with {len(rows)} hives and {len(event_rows)} initial diagnostic events.")


# --- Query Helpers ---

def get_fleet_summary() -> dict:
    """Returns top-level fleet KPI counts."""
    with _get_conn() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM hive_fleet").fetchone()[0]
        healthy  = conn.execute("SELECT COUNT(*) FROM hive_fleet WHERE state = 'NORMAL_HEALTHY'").fetchone()[0]
        warnings = conn.execute("SELECT COUNT(*) FROM hive_fleet WHERE severity IN ('HIGH', 'MEDIUM')").fetchone()[0]
        critical = conn.execute("SELECT COUNT(*) FROM hive_fleet WHERE severity = 'CRITICAL'").fetchone()[0]
    return {"total": total, "healthy": healthy, "warnings": warnings, "critical": critical}


def get_anomaly_counts_by_site():
    """Returns a DataFrame: site | anomaly_count, for anomalous hives only."""
    import pandas as pd
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT site, COUNT(*) AS anomaly_count
            FROM hive_fleet
            WHERE state != 'NORMAL_HEALTHY'
            GROUP BY site
            ORDER BY anomaly_count DESC
        """).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_anomaly_counts_by_type():
    """Returns a DataFrame: state | severity | count, for anomalous hives only."""
    import pandas as pd
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT state, severity, COUNT(*) AS count
            FROM hive_fleet
            WHERE state != 'NORMAL_HEALTHY'
            GROUP BY state
            ORDER BY
                CASE severity
                    WHEN 'CRITICAL' THEN 1
                    WHEN 'HIGH'     THEN 2
                    WHEN 'MEDIUM'   THEN 3
                    ELSE 4
                END
        """).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_triage_queue(severity_filter: list = None, site_filter: list = None):
    """
    Returns a DataFrame of anomalous hives sorted CRITICAL -> HIGH -> MEDIUM.
    Supports optional severity and site filters.
    """
    import pandas as pd
    clauses = ["state != 'NORMAL_HEALTHY'"]
    params: list = []

    if severity_filter:
        placeholders = ",".join("?" * len(severity_filter))
        clauses.append(f"severity IN ({placeholders})")
        params.extend(severity_filter)

    if site_filter:
        placeholders = ",".join("?" * len(site_filter))
        clauses.append(f"site IN ({placeholders})")
        params.extend(site_filter)

    where = " AND ".join(clauses)
    query = f"""
        SELECT hive_id, site, state, severity, action,
               internal_temp_c, hive_weight_kg, edge_acoustic_classification,
               last_eval_ts
        FROM hive_fleet
        WHERE {where}
        ORDER BY
            CASE severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH'     THEN 2
                WHEN 'MEDIUM'   THEN 3
                ELSE 4
            END,
            last_eval_ts DESC
    """
    with _get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_hive_telemetry(hive_id: str) -> dict:
    """Returns a single hive's full telemetry row as a dict, or {} if not found."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM hive_fleet WHERE hive_id = ?", (hive_id,)
        ).fetchone()
    return dict(row) if row else {}


def get_all_sites() -> list:
    """Returns the list of distinct apiary site names."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT site FROM hive_fleet ORDER BY site"
        ).fetchall()
    return [r[0] for r in rows]


def log_diagnostic_event(hive_id: str, evaluation_result: dict, message_id: str = None):
    """
    Inserts the agent's final diagnostic decision into diagnostic_events
    and updates the active state and last_eval_ts in hive_fleet.
    """
    state = evaluation_result.get("state", "NORMAL_HEALTHY")
    severity = evaluation_result.get("severity", "INFO")
    action = evaluation_result.get("action", "Log normal status")
    confidence = float(evaluation_result.get("confidence", 1.0))
    ts = datetime.datetime.now().isoformat(timespec="seconds")

    with _get_conn() as conn:
        conn.execute("""
            INSERT INTO diagnostic_events (hive_id, timestamp, evaluated_state, severity, confidence_score, pubsub_message_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (hive_id, ts, state, severity, confidence, message_id))

        conn.execute("""
            UPDATE hive_fleet
            SET state = ?, severity = ?, action = ?, last_eval_ts = ?
            WHERE hive_id = ?
        """, (state, severity, action, ts, hive_id))


def get_active_alerts(severity_filter: list = None, site_filter: list = None):
    """
    Fetches the most recent critical/warning events from diagnostic_events,
    joining with hive_fleet to get site/telemetry details.
    """
    import pandas as pd

    # We query the latest diagnostic event per hive_id to display the active state
    # joining with hive_fleet to retrieve the site name and telemetry.
    clauses = ["f.state != 'NORMAL_HEALTHY'"]
    params: list = []

    if severity_filter:
        placeholders = ",".join("?" * len(severity_filter))
        clauses.append(f"d.severity IN ({placeholders})")
        params.extend(severity_filter)

    if site_filter:
        placeholders = ",".join("?" * len(site_filter))
        clauses.append(f"f.site IN ({placeholders})")
        params.extend(site_filter)

    where = " AND ".join(clauses)
    query = f"""
        SELECT d.hive_id, f.site, d.evaluated_state AS state, d.severity,
               f.action, f.internal_temp_c, f.hive_weight_kg, 
               f.edge_acoustic_classification, d.timestamp AS last_eval_ts
        FROM (
            SELECT hive_id, MAX(timestamp) as max_ts
            FROM diagnostic_events
            GROUP BY hive_id
        ) latest
        JOIN diagnostic_events d ON d.hive_id = latest.hive_id AND d.timestamp = latest.max_ts
        JOIN hive_fleet f ON d.hive_id = f.hive_id
        WHERE {where}
        ORDER BY
            CASE d.severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'HIGH'     THEN 2
                WHEN 'MEDIUM'   THEN 3
                ELSE 4
            END,
            d.timestamp DESC
    """
    with _get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


# --- Monolith Ephemeral Storage Fallback & Seeding ---

DEFAULT_TEMPERATURE_THRESHOLDS = {
    "brood_temperature_c": {
        "normal": "32-36",
        "warning_low": "<31",
        "warning_high": ">37",
        "critical": ">39"
    }
}

DEFAULT_WEATHER_STATE = {
    "internal_temp_c": 34.41,
    "external_temp_c": 20.45,
    "conditions": "Partly Cloudy",
    "humidity": 50,
    "wind_speed_kmh": 10.0
}

DEFAULT_TELEMETRY_SCHEMA = {
    "state_definitions": {
        "CATASTROPHIC_MASS_LOSS": {
            "required_signals": [
                {
                    "id": "weight_delta_1h",
                    "type": "range",
                    "value": [
                        -100.0,
                        -5.1
                    ]
                }
            ],
            "supporting_signals": [
                {
                    "id": "edge_acoustic_classification",
                    "type": "match",
                    "value": "ERRATIC_MITE_STRESS"
                }
            ],
            "persistence_requirement": 0,
            "severity": "CRITICAL",
            "confidence_override": None,
            "description": "Massive, non-biological weight loss indicating theft, predator interference, or hardware failure. Immediate inspection required."
        },
        "SWARM_DEPARTURE_DETECTED": {
            "required_signals": [
                {
                    "id": "weight_delta_1h",
                    "type": "range",
                    "value": [
                        -5.0,
                        -1.5
                    ]
                },
                {
                    "id": "edge_acoustic_classification",
                    "type": "match",
                    "value": "QUIESCENT"
                }
            ],
            "persistence_requirement": 6,
            "severity": "CRITICAL",
            "confidence_override": None
        },
        "PRE_SWARMING_ALERT": {
            "required_signals": [
                {
                    "id": "edge_acoustic_classification",
                    "type": "match",
                    "value": "PIPING_DETECTED"
                }
            ],
            "supporting_signals": [
                {
                    "id": "weight_trend",
                    "type": "match",
                    "value": "decreasing"
                }
            ],
            "persistence_requirement": 4,
            "severity": "HIGH",
            "confidence_override": None
        },
        "QUEENLESS_COLONY": {
            "required_signals": [
                {
                    "id": "edge_acoustic_classification",
                    "type": "match",
                    "value": "MOURNING_ROAR"
                }
            ],
            "supporting_signals": [
                {
                    "id": "internal_temp_c",
                    "type": "range",
                    "value": [
                        33,
                        35
                    ]
                }
            ],
            "persistence_requirement": 12,
            "severity": "CRITICAL",
            "confidence_override": None
        },
        "COLD_STRESS_ALERT": {
            "required_signals": [
                {
                    "id": "internal_temp_c",
                    "type": "range",
                    "value": [
                        20,
                        31.9
                    ]
                }
            ],
            "persistence_requirement": 2,
            "severity": "HIGH",
            "confidence_override": None
        },
        "PEST_DISTRESS_VARROA": {
            "required_signals": [
                {
                    "id": "edge_acoustic_classification",
                    "type": "match",
                    "value": "ERRATIC_MITE_STRESS"
                },
                {
                    "id": "internal_temp_c",
                    "type": "range",
                    "value": [
                        33,
                        35.5
                    ]
                }
            ],
            "persistence_requirement": 24,
            "severity": "MEDIUM",
            "confidence_override": None
        },
        "HEAT_STRESS_ALERT": {
            "required_signals": [
                {
                    "id": "internal_temp_c",
                    "type": "range",
                    "value": [
                        37,
                        39.9
                    ]
                }
            ],
            "persistence_requirement": 2,
            "severity": "HIGH",
            "confidence_override": None
        },
        "CRITICAL_HEAT_ALERT": {
            "required_signals": [
                {
                    "id": "internal_temp_c",
                    "type": "range",
                    "value": [
                        40,
                        50
                    ]
                }
            ],
            "persistence_requirement": 1,
            "severity": "CRITICAL",
            "confidence_override": None
        },
        "NORMAL_HEALTHY": {
            "required_signals": [
                {
                    "id": "internal_temp_c",
                    "type": "range",
                    "value": [
                        32,
                        36
                    ]
                },
                {
                    "id": "edge_acoustic_classification",
                    "type": "match",
                    "value": "STEADY_HUM"
                }
            ],
            "persistence_requirement": 0,
            "severity": "LOW",
            "confidence_override": None
        }
    },
    "event_resolution": {
        "min_confidence_threshold": 0.75,
        "required_signal_matching": True
    }
}

def ensure_json_files():
    sim_dir = _DB_PATH.parent
    sim_dir.mkdir(parents=True, exist_ok=True)

    thresholds_path = sim_dir / "temperature_thresholds.json"
    if not thresholds_path.exists():
        logger.info(f"Creating default temperature thresholds at {thresholds_path}")
        with open(thresholds_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_TEMPERATURE_THRESHOLDS, f, indent=4)

    weather_path = sim_dir / "weather_state.json"
    if not weather_path.exists():
        logger.info(f"Creating default weather state at {weather_path}")
        with open(weather_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_WEATHER_STATE, f, indent=4)

    schema_path = sim_dir / "telemetry_schema.json"
    if not schema_path.exists():
        logger.info(f"Creating default telemetry schema at {schema_path}")
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_TELEMETRY_SCHEMA, f, indent=4)

def ensure_db_initialized():
    ensure_json_files()
    if not _DB_PATH.exists():
        logger.info(f"Database {_DB_PATH} not found. Seeding fleet database...")
        seed_fleet_database()

# Run initialization upon module import
ensure_db_initialized()

