import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
db_path = Path(__file__).parent.parent.parent / "simulated_data" / "fleet.db"

def test_telemetry_ingest_route():
    # Post mock telemetry payload to FastAPI
    payload = {
        "hive_id": "H-TESTAPI",
        "site": "West_Valley",
        "internal_temp_c": 35.5,
        "external_temp_c": 22.0,
        "edge_acoustic_classification": "STEADY_HUM",
        "hive_weight_kg": 45.0,
        "weight_delta_1h": 0.0
    }
    response = client.post("/api/v1/telemetry/ingest", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # Verify it wrote to database
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT hive_id, site, state FROM hive_fleet WHERE hive_id = 'H-TESTAPI'")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "H-TESTAPI"
    assert row[1] == "West_Valley"
