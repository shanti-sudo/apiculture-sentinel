# ruff: noqa
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

import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

import os
import google.auth

# Lazily determine the project ID at import time if possible, without crashing if credentials are not configured yet
if "GOOGLE_CLOUD_PROJECT" not in os.environ:
    try:
        _, project_id = google.auth.default()
        os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
    except Exception:
        pass

# Respect existing environment settings, defaulting to global Vertex AI if not configured
if "GOOGLE_CLOUD_LOCATION" not in os.environ:
    os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

if "GOOGLE_GENAI_USE_VERTEXAI" not in os.environ:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


import sys

from google.adk.tools.mcp_tool import MCPToolset, StdioConnectionParams
from mcp import StdioServerParameters

# Initialize the MCP toolset to connect to our local weather MCP server
mcp_toolset = MCPToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(os.path.dirname(os.path.dirname(__file__)), "servers", "mcp_server.py")],
        )
    )
)

from agent.skills.state_evaluator import evaluate_hive_state
from agent.skills.pubsub_alerter import publish_alert

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="You are a helpful AI assistant designed to monitor apiary health. Use the get_simulated_weather tool to look up weather details, evaluate_hive_state to analyze telemetry, and publish_alert to send alerts when an anomaly is detected.",
    tools=[mcp_toolset, evaluate_hive_state, publish_alert],
)

app = App(
    root_agent=root_agent,
    name="agent",
)
