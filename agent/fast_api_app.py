# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
import os

import google.auth
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging
from pydantic import BaseModel

from agent.app_utils.telemetry import setup_telemetry
from agent.app_utils.typing import Feedback

setup_telemetry()

# Check if we are running integration tests or if GCP credentials fail
if os.getenv("INTEGRATION_TEST") == "TRUE":
    class MockCloudLogger:
        def log_struct(self, data, severity="INFO"):
            logging.info(f"[{severity}] Mocked Cloud Log: {data}")
    logger = MockCloudLogger()
else:
    try:
        _, project_id = google.auth.default()
        logging_client = google_cloud_logging.Client()
        logger = logging_client.logger(__name__)
    except Exception:
        class MockCloudLogger:
            def log_struct(self, data, severity="INFO"):
                logging.info(f"[{severity}] Fallback Cloud Log: {data}")
        logger = MockCloudLogger()

allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# In-memory session configuration - no persistent storage
session_service_uri = None

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=False if os.getenv("INTEGRATION_TEST") == "TRUE" else True,
)
app.title = "apiculture"
app.description = "API for interacting with the Agent apiculture"


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}




class TelemetryPayload(BaseModel):
    hive_id: str
    site: str
    internal_temp_c: float
    external_temp_c: float
    edge_acoustic_classification: str
    hive_weight_kg: float
    weight_delta_1h: float = 0.0

@app.post("/run")
async def run_evaluation_flat(payload: TelemetryPayload) -> dict:
    """Synchronously evaluates state on telemetry payload and returns flat JSON."""
    from agent.skills.state_evaluator import evaluate_hive_state
    from agent.skills.weather_provider import MCPWeatherProvider

    eval_payload = {
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
    result = await evaluate_hive_state(
        eval_payload,
        weather_provider=MCPWeatherProvider(mcp_client=None),
        memory=None,
        demo_mode=True
    )
    return result


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
