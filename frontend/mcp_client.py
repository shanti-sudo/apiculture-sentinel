"""
Shared MCP Client utilities.
Provides MCPClientManager and initialization helpers used by both
app.py (landing page) and pages/hive_triage.py.
"""

import asyncio
import json
import logging
import sys
import threading
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPClientManager:
    """
    Maintains a persistent stdio MCP client session in a background thread.
    Shared via st.session_state so the subprocess is spawned once per browser
    session, not on every Streamlit rerun.
    """

    def __init__(self, server_path: Path):
        self.server_path = server_path
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

        self.ready_event = threading.Event()
        self.shutdown_event = None
        self.session = None
        self.error = None

        self.loop.call_soon_threadsafe(
            lambda: self.loop.create_task(self._main_task())
        )

        if not self.ready_event.wait(timeout=15.0):
            raise RuntimeError(f"MCP client failed to initialize: {self.error or 'timeout'}")

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    async def _main_task(self):
        self.shutdown_event = asyncio.Event()
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(self.server_path)],
            env=None,
        )
        try:
            async with AsyncExitStack() as stack:
                read_stream, write_stream = await stack.enter_async_context(
                    stdio_client(server_params)
                )
                self.session = await stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await self.session.initialize()
                self.ready_event.set()
                await self.shutdown_event.wait()
        except Exception as e:
            self.error = e
            self.ready_event.set()

    def close(self):
        if self.shutdown_event:
            self.loop.call_soon_threadsafe(self.shutdown_event.set)
        self.loop.call_later(0.5, self.loop.stop)
        self.thread.join(timeout=2.0)


def ensure_mcp_initialized(server_path: Path):
    """
    Idempotent — initializes the MCPClientManager into st.session_state
    exactly once per browser session.
    """
    import streamlit as st
    if "mcp_manager" not in st.session_state:
        try:
            st.session_state.mcp_manager = MCPClientManager(server_path)
        except Exception as e:
            logger.error(f"Failed to start MCP Client Manager: {e}")
            st.session_state.mcp_manager = None
            st.session_state.mcp_manager_error = str(e)


async def get_mcp_environmental_context() -> dict:
    """
    Fetches the current simulated weather context via the persistent MCP session.
    Falls back to the source JSON file on any failure to avoid hardcoding defaults.
    """
    import streamlit as st
    from pathlib import Path
    
    # Resolve project root and locate source JSON file
    project_root = Path(__file__).parent.parent
    source_json_path = project_root / "simulated_data" / "weather_state.json"
    
    _fallback = {
        "external_temp_c": 20.0,
        "conditions": "Sunny",
        "humidity": 50.0,
        "wind_speed_kmh": 10.0,
    }
    
    if source_json_path.exists():
        try:
            with open(source_json_path, encoding="utf-8") as f:
                data = json.load(f)
                for k, v in data.items():
                    _fallback[k] = v
        except Exception as e:
            logger.error(f"Failed to read source weather_state.json fallback: {e}")
            
    try:
        manager = st.session_state.get("mcp_manager")
        if not manager or not manager.session:
            raise RuntimeError("MCP Client Manager unavailable.")
        future = asyncio.run_coroutine_threadsafe(
            manager.session.call_tool("get_simulated_weather", {"location": "main_apiary"}),
            manager.loop,
        )
        result = await asyncio.wrap_future(future)
        if result and result.content:
            content_text = result.content[0].text
            try:
                return json.loads(content_text)
            except Exception:
                import ast
                return ast.literal_eval(content_text)
    except Exception as e:
        logger.warning(f"Failed to get MCP environmental context: {e}. Using source weather_state.json fallback.")
    return _fallback


async def get_mcp_telemetry_schema() -> dict:
    """
    Fetches the telemetry schema via MCP; falls back to local JSON file on failure.
    """
    import streamlit as st
    try:
        manager = st.session_state.get("mcp_manager")
        if not manager or not manager.session:
            raise RuntimeError("MCP Client Manager unavailable.")
        future = asyncio.run_coroutine_threadsafe(
            manager.session.call_tool("get_telemetry_schema", {}),
            manager.loop,
        )
        result = await asyncio.wrap_future(future)
        if result and result.content:
            content_text = result.content[0].text
            try:
                return json.loads(content_text)
            except Exception:
                import ast
                return ast.literal_eval(content_text)
    except Exception as e:
        logger.warning(f"Failed to get MCP telemetry schema: {e}. Falling back to local schema.")

    # Local file fallback
    schema_path = Path(__file__).parent.parent / "simulated_data" / "telemetry_schema.json"
    try:
        with open(schema_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as io_err:
        logger.error(f"Failed to read local telemetry schema: {io_err}")
    return {
        "pitch_profiles": ["steady", "high_pitch_piping", "mourning_roar", "erratic_spikes", "sluggish"],
        "telemetry_simulations": [],
    }
