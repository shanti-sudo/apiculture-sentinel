"""
Agent Skill: Sentinel Memory
Purpose: Stores historical patterns and records past observations to form the
         long-term memory layer of the Agentic Sentinel.
"""

import datetime
import logging

logger = logging.getLogger(__name__)

class SentinelMemory:
    """
    Tracks historical patterns and runtime observations to provide contextual reasoning.
    """
    def __init__(self):
        self.observations = []
        self.historical_patterns = {
            "weight_trend": "This hive normally increases weight every April",
            "heat_stress_trend": "This location has heat stress every afternoon"
        }

    def get_context(self) -> dict:
        """
        Retrieves the historical patterns and past observations context.
        """
        return {
            "historical_patterns": self.historical_patterns,
            "past_observations": self.observations
        }

    def add_observation(self, state: str, explanation: str, telemetry: dict = None):
        """
        Adds an observation to memory, enabling a closed feedback loop.
        """
        observation = {
            "timestamp": datetime.datetime.now().isoformat(),
            "state": state,
            "explanation": explanation
        }
        if telemetry is not None:
            observation["telemetry"] = telemetry

        self.observations.append(observation)
        logger.info(f"SentinelMemory: Recorded observation: {state} | {explanation}")
