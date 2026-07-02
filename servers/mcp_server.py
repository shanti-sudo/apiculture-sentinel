"""
MCP Server: Apiculture Weather Simulation Server
Purpose: Exposes simulated weather tools for the Apiculture agent via Model Context Protocol (MCP).
Design: Implements the official python mcp SDK (using FastMCP). Reads simulated state from a local JSON file 
        to coordinate dynamic updates from the Streamlit user interface in real-time.
"""

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Define the path to the shared simulation state file
# This allows the Streamlit UI process and the MCP Server process to share state.
STATE_FILE_PATH = Path(__file__).parent.parent / "simulated_data" / "weather_state.json"
SCHEMA_FILE_PATH = Path(__file__).parent.parent / "simulated_data" / "telemetry_schema.json"

# Initialize FastMCP Server
mcp = FastMCP("Apiculture Weather Simulation Server")

@mcp.tool()
def get_simulated_weather(location: str = "main_apiary") -> dict:
    """
    Retrieves the current simulated weather metrics for the apiary.
    
    This tool reads the active simulated state (which is updated dynamically
    by user input / sliders in the UI) to determine weather metrics like external temperature.
    
    Args:
        location (str): The name or identifier of the apiary location. Defaults to 'main_apiary'.
        
    Returns:
        dict: A dictionary containing:
            - 'location': The queried location name.
            - 'external_temp_c': The current simulated external temperature in Celsius.
            - 'conditions': The current weather conditions (e.g. Sunny, Cold, Rainy).
            - 'humidity': Simulated relative humidity percentage.
            - 'wind_speed_kmh': Simulated wind speed in km/h.
    """
    # Default fallback weather state
    default_weather = {
        "location": location,
        "internal_temp_c": 35.0,
        "external_temp_c": 20.0,
        "conditions": "Sunny",
        "humidity": 50.0,
        "wind_speed_kmh": 10.0
    }

    if not STATE_FILE_PATH.exists():
        return default_weather

    try:
        with open(STATE_FILE_PATH, encoding="utf-8") as f:
            state = json.load(f)

        # Merge values directly from the state JSON root, using defaults for anything missing
        weather_data = {
            "location": location,
            "internal_temp_c": float(state.get("internal_temp_c", default_weather["internal_temp_c"])),
            "external_temp_c": float(state.get("external_temp_c", default_weather["external_temp_c"])),
            "conditions": str(state.get("conditions", default_weather["conditions"])),
            "humidity": float(state.get("humidity", default_weather["humidity"])),
            "wind_speed_kmh": float(state.get("wind_speed_kmh", default_weather["wind_speed_kmh"]))
        }
        return weather_data

    except Exception as e:
        # Fallback to defaults if there's any file reading/parsing error
        # In stdio transport, print() should not be used as it will corrupt stdio.
        # We can write to stderr if needed or simply return default_weather.
        import sys
        sys.stderr.write(f"Error reading simulation state file: {e}\n")
        return default_weather

@mcp.tool()
def get_telemetry_schema() -> dict:
    """
    Retrieves the simulated telemetry schema containing pitch profiles and mock configurations.
    
    Returns:
        dict: The parsed JSON schema.
    """
    default_schema = {
        "pitch_profiles": ["steady", "high_pitch_piping", "mourning_roar", "erratic_spikes", "sluggish"],
        "telemetry_simulations": []
    }
    if not SCHEMA_FILE_PATH.exists():
        return default_schema
    try:
        with open(SCHEMA_FILE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        import sys
        sys.stderr.write(f"Error reading telemetry schema file: {e}\n")
        return default_schema

if __name__ == "__main__":
    # Start the FastMCP server on stdio transport
    mcp.run(transport="stdio")
