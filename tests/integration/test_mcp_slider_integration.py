"""
Integration Test: MCP Slider State Propagation
Purpose: Simulates user actions in Streamlit UI (updating weather_state.json via sliders)
         and verifies that evaluate_hive_state fetches the updated values dynamically 
         through the MCP server.
"""

import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent.skills.state_evaluator import evaluate_hive_state
from agent.skills.weather_provider import MCPWeatherProvider

# Paths
WEATHER_STATE_FILE = PROJECT_ROOT / "simulated_data" / "weather_state.json"
SERVER_PATH = PROJECT_ROOT / "servers" / "mcp_server.py"

async def run_mcp_test():
    # 1. Back up original weather state
    original_state = {}
    if WEATHER_STATE_FILE.exists():
        with open(WEATHER_STATE_FILE, encoding="utf-8") as f:
            original_state = json.load(f)

    try:
        # Define mock telemetry payload
        telemetry_payload = {
            "edge_acoustic_classification": "STEADY_HUM",
            "acoustic_metrics": {
                "edge_acoustic_classification": "STEADY_HUM"
            },
            "environmental_metrics": {}
        }

        # 2. Simulate User Action: Slide External Temperature to -5.0°C and Internal to 30.0°C (Cold Stress warning)
        simulated_slider_state = {
            "internal_temp_c": 30.0,
            "external_temp_c": -5.0,
            "conditions": "freezing_rain",
            "humidity": 80.0,
            "wind_speed_kmh": 25.0
        }
        with open(WEATHER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(simulated_slider_state, f, indent=4)

        print("[Test] Simulated slider update: set external_temp_c to -5.0")

        # 3. Setup MCP connection parameters
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER_PATH)],
            env=None
        )

        # 4. Connect to MCP server and run evaluation
        async with AsyncExitStack() as stack:
            print("[Test] Connecting to local MCP server...")
            read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))

            print("[Test] Initializing MCP Session...")
            await session.initialize()

            print("[Test] Invoking evaluate_hive_state skill with active MCP client...")
            weather_provider = MCPWeatherProvider(mcp_client=session)
            result = await evaluate_hive_state(telemetry_payload, weather_provider=weather_provider)

            print("[Test] Evaluation result:", result)

            # Assertions to verify the cold stress alert is detected because external_temp was retrieved as -5.0
            assert result["state"] == "COLD_STRESS_ALERT"
            assert result["action"] == "Publish Thermal Blanket Request"
            assert result["severity"] == "HIGH"

        # 5. Simulate User Action: Slide External Temperature to 25.0°C (Warm condition)
        simulated_slider_state["external_temp_c"] = 25.0
        with open(WEATHER_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(simulated_slider_state, f, indent=4)

        print("[Test] Simulated slider update: set external_temp_c to 25.0")

        # 6. Re-evaluate with the same session
        async with AsyncExitStack() as stack:
            read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
            session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await session.initialize()

            weather_provider = MCPWeatherProvider(mcp_client=session)
            result = await evaluate_hive_state(telemetry_payload, weather_provider=weather_provider)
            print("[Test] Evaluation result after warm temperature update:", result)

            # Assertions to verify it now falls back to NORMAL_HEALTHY because temperature is warm (25.0C)
            assert result["state"] == "NORMAL_HEALTHY"

    finally:
        # Restore original weather state file
        if original_state:
            with open(WEATHER_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(original_state, f, indent=4)
        print("[Test] Cleanup complete: restored original weather_state.json")

if __name__ == "__main__":
    asyncio.run(run_mcp_test())
