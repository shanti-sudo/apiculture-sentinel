import sqlite3
import subprocess
import time
from pathlib import Path

import requests

db_path = Path(__file__).parent.parent / "simulated_data" / "fleet.db"

def check_hive(hive_id):
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT state, severity, internal_temp_c, last_eval_ts FROM hive_fleet WHERE hive_id = ?", (hive_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def main():
    print("Starting FastAPI Server via Uvicorn...")
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "main:app", "--port", "8000", "--host", "127.0.0.1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(3.0)  # Wait for startup

    try:
        url = "http://127.0.0.1:8000/api/v1/telemetry/ingest"

        # Test Case 1: Ingesting critical heat anomaly
        payload_anomaly = {
            "hive_id": "H-99999",
            "site": "North_Field",
            "internal_temp_c": 43.5,
            "external_temp_c": 35.0,
            "edge_acoustic_classification": "STEADY_HUM",
            "hive_weight_kg": 40.0,
            "weight_delta_1h": 0.0
        }
        print("Posting anomalous telemetry payload...")
        resp = requests.post(url, json=payload_anomaly)
        print(f"Response: {resp.status_code} | {resp.json()}")

        # Wait for async background task to complete
        time.sleep(2.0)

        row = check_hive("H-99999")
        print(f"Verified Database state for H-99999: {row}")

    finally:
        print("Shutting down FastAPI Server...")
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    main()
