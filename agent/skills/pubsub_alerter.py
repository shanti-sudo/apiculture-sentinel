"""
Agent Skill: Pub/Sub Alerter
Purpose: Reusable module to publish alert messages to Google Cloud Pub/Sub.

Design: This acts as the "action engine" of the agent. It receives evaluated 
hive health anomalies and routes them to a GCP Pub/Sub topic.
"""

import json
import logging
import os

import google.auth
import google.auth.transport.requests
from google.cloud import pubsub_v1

# Setup module-level logger
logger = logging.getLogger(__name__)

def get_pubsub_publisher():
    """
    Initializes and returns a Pub/Sub Publisher Client.
    Validates credentials beforehand to ensure application defaults are authenticated and refreshable.
    """
    try:
        credentials, project = google.auth.default()
        # Verify credentials can get an access token
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)
        return pubsub_v1.PublisherClient(credentials=credentials)
    except Exception as e:
        logger.warning(f"Failed to initialize GCP Pub/Sub publisher: credentials not authenticated or expired: {e}")
        return None

def publish_alert(state: str, action: str, severity: str) -> str:
    """
    Publishes an evaluated alert to the GCP Pub/Sub topic.
    
    Args:
        state (str): The evaluated hive state (e.g. COLD_STRESS_ALERT).
        action (str): The recommended action (e.g. Publish Thermal Blanket Request).
        severity (str): The alert severity (e.g. HIGH, CRITICAL).
        
    Returns:
        str: The published message ID, or a mock confirmation ID if local/unauthenticated.
    """
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "mock-project")
    topic_id = os.getenv("PUBSUB_TOPIC_ID", "apiculture-alerts")

    # Fully qualified topic path
    topic_path = f"projects/{project_id}/topics/{topic_id}"

    message_data = {
        "state": state,
        "action": action,
        "severity": severity
    }

    # Serialize payload to JSON bytes
    try:
        data = json.dumps(message_data).encode("utf-8")
    except Exception as e:
        logger.error(f"Failed to serialize message data: {e} | context: {message_data}")
        raise

    try:
        publisher = get_pubsub_publisher()
        if publisher is not None and project_id != "mock-project":
            logger.info(f"Publishing alert to Pub/Sub topic {topic_path} | context: {message_data}")
            future = publisher.publish(topic_path, data)
            message_id = future.result(timeout=2.0)
            logger.info(f"Successfully published alert (ID: {message_id})")
            return message_id
        else:
            logger.info("Pub/Sub publisher client unavailable or using mock project. Falling back to local simulation.")
    except Exception as e:
        logger.warning(f"Error publishing alert to GCP Pub/Sub: {e} | context: {message_data}. Falling back to mock publication.")

    # Mock confirmation for local simulation/dry-runs to guarantee a deterministic environment
    import uuid
    mock_id = f"mock-msg-{uuid.uuid4().hex[:8]}"
    logger.info(f"[Local Simulation] Published to {topic_path} (ID: {mock_id}) | context: {message_data}")
    return mock_id

if __name__ == "__main__":
    # Configure logging for main runner
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] (%(name)s) %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S%z'
    )
    # Test publishing a mock alert
    msg_id = publish_alert("COLD_STRESS_ALERT", "Publish Thermal Blanket Request", "HIGH")
    logger.info(f"Message ID: {msg_id}")
