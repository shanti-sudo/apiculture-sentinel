import pytest
import datetime

from agent.skills.sentinel_memory import SentinelMemory
from agent.skills.state_evaluator import evaluate_hive_state
from agent.skills.weather_provider import WeatherProvider


class MockWeatherProvider(WeatherProvider):
    async def get_weather_context(self) -> dict:
        return {
            "internal_temp_c": 35.0,
            "external_temp_c": 20.0,
            "conditions": "Sunny",
            "humidity": 50.0,
            "wind_speed_kmh": 10.0
        }

def seed_memory(memory: SentinelMemory):
    memory.add_observation(
        state="INITIALIZING_MONITORING",
        explanation="Initial healthy state",
        telemetry={
            "edge_acoustic_classification": "STEADY_HUM",
            "acoustic_metrics": {"edge_acoustic_classification": "STEADY_HUM"},
            "environmental_metrics": {"internal_temp_c": 35.0},
            "weight_metrics": {"hive_weight_kg": 40.0}
        }
    )
    memory.observations[-1]["timestamp"] = (datetime.datetime.now() - datetime.timedelta(hours=10)).isoformat()

@pytest.mark.anyio
async def test_first_run_initializing():
    # First-run telemetry with no history returns INITIALIZING_MONITORING
    payload = {
        "edge_acoustic_classification": "STEADY_HUM",
        "acoustic_metrics": {
            "edge_acoustic_classification": "STEADY_HUM"
        },
        "environmental_metrics": {
            "internal_temp_c": 35.0
        },
        "weight_metrics": {
            "hive_weight_kg": 40.0
        }
    }
    memory = SentinelMemory()
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory)
    assert result["state"] == "INITIALIZING_MONITORING"
    assert result["confidence"] == 0.5
    assert "establishing baseline" in result["explanation"].lower()

@pytest.mark.anyio
async def test_first_run_extreme_override():
    # First-run telemetry with extreme weight drop (>5kg) overrides initialization
    payload = {
        "edge_acoustic_classification": "ERRATIC_MITE_STRESS",
        "acoustic_metrics": {
            "edge_acoustic_classification": "ERRATIC_MITE_STRESS"
        },
        "environmental_metrics": {
            "internal_temp_c": 35.0
        },
        "weight_metrics": {
            "hive_weight_kg": 34.0,
            "weight_delta_1h": -6.0
        }
    }
    memory = SentinelMemory()
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory)
    assert result["state"] == "CATASTROPHIC_MASS_LOSS"
    assert result["confidence"] == 0.5
    assert "immediate attention required despite limited history" in result["explanation"].lower()

@pytest.mark.anyio
async def test_cold_stress_alert():
    # Cold Stress Alert: internal_temp_c < 32.0
    payload = {
        "edge_acoustic_classification": "STEADY_HUM",
        "acoustic_metrics": {
            "edge_acoustic_classification": "STEADY_HUM"
        },
        "environmental_metrics": {
            "internal_temp_c": 31.0,
            "external_temp_c": 5.0
        }
    }

    memory = SentinelMemory()
    seed_memory(memory)
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory, demo_mode=True)

    assert result["state"] == "COLD_STRESS_ALERT"
    assert result["action"] == "Publish Thermal Blanket Request"
    assert result["severity"] == "HIGH"

    # Check memory observation
    assert len(memory.observations) == 2
    obs = memory.observations[-1]
    assert obs["state"] == "COLD_STRESS_ALERT"
    assert "internal temperature is 31.0" in obs["explanation"].lower()

@pytest.mark.anyio
async def test_swarm_preparation():
    # PRE_SWARMING_ALERT: PIPING_DETECTED
    payload = {
        "edge_acoustic_classification": "PIPING_DETECTED",
        "acoustic_metrics": {
            "edge_acoustic_classification": "PIPING_DETECTED"
        },
        "environmental_metrics": {
            "internal_temp_c": 35.0
        }
    }

    memory = SentinelMemory()
    seed_memory(memory)
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory, demo_mode=True)

    assert result["state"] == "PRE_SWARMING_ALERT"
    assert result["action"] == "Trigger Space Inspection Alert"
    assert result["severity"] == "HIGH"

@pytest.mark.anyio
async def test_pest_distress_varroa():
    # PEST_DISTRESS_VARROA: internal_temp_c in [33, 35.5], edge_acoustic_classification matches ERRATIC_MITE_STRESS
    payload = {
        "edge_acoustic_classification": "ERRATIC_MITE_STRESS",
        "acoustic_metrics": {
            "edge_acoustic_classification": "ERRATIC_MITE_STRESS"
        },
        "environmental_metrics": {
            "internal_temp_c": 34.0
        }
    }

    memory = SentinelMemory()
    seed_memory(memory)
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory, demo_mode=True)

    assert result["state"] == "PEST_DISTRESS_VARROA"
    assert result["action"] == "Trigger Pest Inspection Alert"
    assert result["severity"] == "MEDIUM"


@pytest.mark.anyio
async def test_pest_distress_varroa_persistence():
    payload = {
        "edge_acoustic_classification": "ERRATIC_MITE_STRESS",
        "acoustic_metrics": {
            "edge_acoustic_classification": "ERRATIC_MITE_STRESS"
        },
        "environmental_metrics": {
            "internal_temp_c": 34.0
        }
    }

    # Setup SentinelMemory with a NORMAL_HEALTHY observation in the window
    memory = SentinelMemory()
    memory.add_observation(
        state="NORMAL_HEALTHY",
        explanation="normal status",
        telemetry={
            "edge_acoustic_classification": "STEADY_HUM",
            "acoustic_metrics": {"edge_acoustic_classification": "STEADY_HUM"},
            "environmental_metrics": {"internal_temp_c": 35.0}
        }
    )

    wp = MockWeatherProvider()
    # Should fall back to NORMAL_HEALTHY because the past observation within the 24h window does not match Varroa signals
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory)
    assert result["state"] == "NORMAL_HEALTHY"
    assert "PEST_DISTRESS_VARROA" in result["explanation"]
    assert "persistence" in result["explanation"]


@pytest.mark.anyio
async def test_normal_healthy():
    payload = {
        "edge_acoustic_classification": "STEADY_HUM",
        "acoustic_metrics": {
            "edge_acoustic_classification": "STEADY_HUM"
        },
        "environmental_metrics": {
            "internal_temp_c": 35.0
        }
    }

    memory = SentinelMemory()
    seed_memory(memory)
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory, demo_mode=True)

    assert result["state"] == "NORMAL_HEALTHY"
    assert result["action"] == "Log normal status"
    assert result["severity"] == "INFO"


@pytest.mark.anyio
async def test_production_resilience():
    # Passing None to trigger AttributeError in evaluate_hive_state
    result = await evaluate_hive_state(None)

    assert result["state"] == "ERROR"
    assert result["severity"] == "CRITICAL"
    assert "Error" in result["action"]
    assert "explanation" in result

def test_spatial_compliance():
    from agent.skills.spatial_manager import ApiarySpatialManager
    payload = {
        "total_sq_ft": 100.0,
        "num_hives": 6  # max is 5 (100 / 20)
    }
    mgr = ApiarySpatialManager()
    report = mgr.validate_layout(payload)

    assert not report["compliant"]
    assert report["max_hives"] == 5
    assert report["excess_hives"] == 1


@pytest.mark.anyio
async def test_swarm_departure_first_run():
    # Swarm departure check on empty memory returns INITIALIZING_MONITORING
    payload = {
        "edge_acoustic_classification": "QUIESCENT",
        "acoustic_metrics": {
            "edge_acoustic_classification": "QUIESCENT"
        },
        "environmental_metrics": {
            "internal_temp_c": 35.0
        },
        "weight_metrics": {
            "hive_weight_kg": 27.0
        }
    }
    memory = SentinelMemory()
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory)
    assert result["state"] == "INITIALIZING_MONITORING"


@pytest.mark.anyio
async def test_swarm_departure_second_run():
    memory = SentinelMemory()

    # Add initial observation (weight = 40.0)
    memory.add_observation(
        state="NORMAL_HEALTHY",
        explanation="Initial healthy state",
        telemetry={
            "edge_acoustic_classification": "STEADY_HUM",
            "acoustic_metrics": {"edge_acoustic_classification": "STEADY_HUM"},
            "environmental_metrics": {"internal_temp_c": 35.0},
            "weight_metrics": {"hive_weight_kg": 40.0}
        }
    )
    # Move this first observation out of the 6-hour persistence window (set to 10 hours ago)
    memory.observations[0]["timestamp"] = (datetime.datetime.now() - datetime.timedelta(hours=10)).isoformat()

    # Add intermediate observation within persistence window showing weight loss of 2kg (weight = 38.0, delta = -2.0)
    memory.add_observation(
        state="NORMAL_HEALTHY",
        explanation="Slight weight loss",
        telemetry={
            "edge_acoustic_classification": "QUIESCENT",
            "acoustic_metrics": {"edge_acoustic_classification": "QUIESCENT"},
            "environmental_metrics": {"internal_temp_c": 35.0},
            "weight_metrics": {"hive_weight_kg": 38.0, "weight_delta_1h": -2.0}
        }
    )

    # Current payload: weight = 36.0 (delta from intermediate is 36.0 - 38.0 = -2.0)
    payload = {
        "edge_acoustic_classification": "QUIESCENT",
        "acoustic_metrics": {
            "edge_acoustic_classification": "QUIESCENT"
        },
        "environmental_metrics": {
            "internal_temp_c": 35.0
        },
        "weight_metrics": {
            "hive_weight_kg": 36.0
        }
    }

    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory)
    assert result["state"] == "SWARM_DEPARTURE_DETECTED"
    assert result["action"] == "Dispatch Swarm Recovery Protocol"
    assert result["severity"] == "CRITICAL"


@pytest.mark.anyio
async def test_catastrophic_mass_loss():
    memory = SentinelMemory()

    # Add initial observation (weight = 40.0)
    memory.add_observation(
        state="NORMAL_HEALTHY",
        explanation="Initial healthy state",
        telemetry={
            "edge_acoustic_classification": "STEADY_HUM",
            "acoustic_metrics": {"edge_acoustic_classification": "STEADY_HUM"},
            "environmental_metrics": {"internal_temp_c": 35.0},
            "weight_metrics": {"hive_weight_kg": 40.0}
        }
    )

    # Current payload: weight = 28.0 (delta is 28.0 - 40.0 = -12.0)
    # Acoustic classification is ERRATIC_MITE_STRESS (supporting signal)
    payload = {
        "edge_acoustic_classification": "ERRATIC_MITE_STRESS",
        "acoustic_metrics": {
            "edge_acoustic_classification": "ERRATIC_MITE_STRESS"
        },
        "environmental_metrics": {
            "internal_temp_c": 35.0
        },
        "weight_metrics": {
            "hive_weight_kg": 28.0
        }
    }

    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory)
    assert result["state"] == "CATASTROPHIC_MASS_LOSS"
    assert result["action"] == "Trigger Emergency Apiary Investigation"
    assert result["severity"] == "CRITICAL"
    assert "non-biological" in result["explanation"].lower()


@pytest.mark.anyio
async def test_demo_mode_bypass():
    # Setup SentinelMemory with a NORMAL_HEALTHY observation in the window
    memory = SentinelMemory()
    memory.add_observation(
        state="NORMAL_HEALTHY",
        explanation="normal status",
        telemetry={
            "edge_acoustic_classification": "STEADY_HUM",
            "acoustic_metrics": {"edge_acoustic_classification": "STEADY_HUM"},
            "environmental_metrics": {"internal_temp_c": 35.0}
        }
    )

    payload = {
        "edge_acoustic_classification": "ERRATIC_MITE_STRESS",
        "acoustic_metrics": {
            "edge_acoustic_classification": "ERRATIC_MITE_STRESS"
        },
        "environmental_metrics": {
            "internal_temp_c": 34.0
        }
    }

    wp = MockWeatherProvider()

    # 1. With demo_mode=False, it should fail persistence and fall back to NORMAL_HEALTHY
    result_normal = await evaluate_hive_state(payload, weather_provider=wp, memory=memory, demo_mode=False)
    assert result_normal["state"] == "NORMAL_HEALTHY"

    # 2. With demo_mode=True, it should bypass persistence and immediately trigger PEST_DISTRESS_VARROA
    result_demo = await evaluate_hive_state(payload, weather_provider=wp, memory=memory, demo_mode=True)
    assert result_demo["state"] == "PEST_DISTRESS_VARROA"
    assert "DEMO MODE ACTIVE" in result_demo["explanation"]


@pytest.mark.anyio
async def test_heat_stress_alert():
    # Heat Stress Alert: internal_temp_c in [37.0, 39.9]
    payload = {
        "edge_acoustic_classification": "STEADY_HUM",
        "acoustic_metrics": {
            "edge_acoustic_classification": "STEADY_HUM"
        },
        "environmental_metrics": {
            "internal_temp_c": 38.0
        }
    }

    memory = SentinelMemory()
    seed_memory(memory)
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory, demo_mode=True)

    assert result["state"] == "HEAT_STRESS_ALERT"
    assert result["action"] == "Trigger Hive Ventilation Alert"
    assert result["severity"] == "HIGH"


@pytest.mark.anyio
async def test_critical_heat_alert():
    # Critical Heat Alert: internal_temp_c >= 40.0
    payload = {
        "edge_acoustic_classification": "STEADY_HUM",
        "acoustic_metrics": {
            "edge_acoustic_classification": "STEADY_HUM"
        },
        "environmental_metrics": {
            "internal_temp_c": 41.0
        }
    }

    memory = SentinelMemory()
    seed_memory(memory)
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory, demo_mode=True)

    assert result["state"] == "CRITICAL_HEAT_ALERT"
    assert result["action"] == "Trigger Critical Cooling Request"
    assert result["severity"] == "CRITICAL"


class MockCloudyWeatherProvider(WeatherProvider):
    async def get_weather_context(self) -> dict:
        return {
            "internal_temp_c": 35.0,
            "external_temp_c": 20.0,
            "conditions": "Partly Cloudy",
            "humidity": 50.0,
            "wind_speed_kmh": 10.0
        }


@pytest.mark.anyio
async def test_critical_heat_alert_downgrade():
    payload = {
        "edge_acoustic_classification": "STEADY_HUM",
        "acoustic_metrics": {
            "edge_acoustic_classification": "STEADY_HUM"
        },
        "environmental_metrics": {
            "internal_temp_c": 41.0
        }
    }

    memory = SentinelMemory()
    seed_memory(memory)
    wp = MockCloudyWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory, demo_mode=True)

    assert result["state"] == "HEAT_STRESS_ALERT"
    assert result["action"] == "Trigger Hive Ventilation Alert"
    assert result["severity"] == "HIGH"


def test_spatial_clearance_violations():
    from agent.skills.spatial_manager import ApiarySpatialManager
    payload = {
        "total_sq_ft": 100.0,
        "hives": [
            {"hive_id": "hive_1", "clearance_front_ft": 5.5, "clearance_back_ft": 3.0, "clearance_sides_ft": 3.0},
            {"hive_id": "hive_2", "clearance_front_ft": 4.5, "clearance_back_ft": 3.0, "clearance_sides_ft": 3.2}, # Intentional violation: front < 5.0
            {"hive_id": "hive_3", "clearance_front_ft": 5.0, "clearance_back_ft": 2.5, "clearance_sides_ft": 2.8}  # Intentional violations: back < 3.0, sides < 3.0
        ]
    }
    mgr = ApiarySpatialManager()
    report = mgr.validate_layout(payload)

    assert report["status"] == "REJECTED"
    assert report["compliant_hives"] == 1
    assert len(report["violations"]) == 2

    violations_map = {v["hive_id"]: v["reasons"] for v in report["violations"]}
    assert "hive_2" in violations_map
    assert "hive_3" in violations_map
    assert any("Front clearance" in r for r in violations_map["hive_2"])
    assert any("Rear clearance" in r for r in violations_map["hive_3"])
    assert any("Side clearance" in r for r in violations_map["hive_3"])


@pytest.mark.anyio
async def test_initializing_monitoring_fallback():
    # If previous state was INITIALIZING_MONITORING and current telemetry is normal, it stays in INITIALIZING_MONITORING
    payload = {
        "edge_acoustic_classification": "STEADY_HUM",
        "acoustic_metrics": {
            "edge_acoustic_classification": "STEADY_HUM"
        },
        "environmental_metrics": {
            "internal_temp_c": 35.0
        },
        "weight_metrics": {
            "hive_weight_kg": 40.0
        }
    }
    memory = SentinelMemory()
    memory.add_observation(
        state="INITIALIZING_MONITORING",
        explanation="Establishing baseline",
        telemetry=payload
    )
    wp = MockWeatherProvider()
    result = await evaluate_hive_state(payload, weather_provider=wp, memory=memory)
    assert result["state"] == "INITIALIZING_MONITORING"
    assert "establishing baseline" in result["reason"].lower()
