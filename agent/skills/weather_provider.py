"""
Weather Provider Pattern Architecture
Purpose: Decouples the apiary health reasoning layer from the underlying data fetching implementation.
"""

import ast
import json
import logging
import sys
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Module level logger
logger = logging.getLogger(__name__)

# Absolute path to the MCP weather server
SERVER_PATH = Path(__file__).parent.parent.parent / "servers" / "mcp_server.py"

class WeatherProvider(ABC):
    """
    Abstract Base Class for weather context provisioning.
    """
    @abstractmethod
    async def get_weather_context(self) -> dict:
        """
        Abstract method to retrieve the simulated or real external weather context.
        
        Returns:
            dict: Dictionary containing weather metrics (e.g., external_temp_c, humidity, conditions).
        """
        pass

class MCPWeatherProvider(WeatherProvider):
    """
    Concrete implementation of WeatherProvider that queries the local MCP weather server.
    """
    def __init__(self, mcp_client: ClientSession = None, location: str = "main_apiary"):
        """
        Initializes the provider with an optional active MCP ClientSession.
        
        Args:
            mcp_client (ClientSession, optional): Reusable active MCP ClientSession.
            location (str): The apiary location identifier. Defaults to 'main_apiary'.
        """
        self.mcp_client = mcp_client
        self.location = location

    async def get_weather_context(self) -> dict:
        """
        Fetches the current weather context from the local MCP weather server.
        Uses the provided ClientSession if available; otherwise, spawns a transient stdio client connection.
        
        Returns:
            dict: Merged or retrieved weather metrics with safe defaults.
        """
        fallback_weather = {
            "internal_temp_c": 35.0,
            "external_temp_c": 20.0,
            "conditions": "Sunny",
            "humidity": 50.0,
            "wind_speed_kmh": 10.0
        }

        # Case 1: Reusable active client session is provided (e.g., during live app operations or tests)
        if self.mcp_client is not None:
            try:
                result = await self.mcp_client.call_tool("get_simulated_weather", arguments={"location": self.location})
                if result and result.content:
                    content_text = result.content[0].text
                    try:
                        return json.loads(content_text)
                    except Exception:
                        try:
                            return ast.literal_eval(content_text)
                        except Exception as parse_err:
                            logger.error(f"Failed to parse active MCP response: {parse_err}")
            except Exception as e:
                logger.error(f"Error calling MCP tool via active client: {e}")
            return fallback_weather

        # Case 2: No active session is provided. Spawn a transient stdio connection.
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER_PATH)],
            env=None
        )

        try:
            async with AsyncExitStack() as stack:
                read_stream, write_stream = await stack.enter_async_context(stdio_client(server_params))
                session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
                await session.initialize()

                result = await session.call_tool("get_simulated_weather", arguments={"location": self.location})
                if result and result.content:
                    content_text = result.content[0].text
                    try:
                        return json.loads(content_text)
                    except Exception:
                        try:
                            return ast.literal_eval(content_text)
                        except Exception as parse_err:
                            logger.error(f"Failed to parse transient MCP response: {parse_err}")
        except Exception as e:
            logger.error(f"Error querying transient MCP weather server: {e}")

        return fallback_weather
