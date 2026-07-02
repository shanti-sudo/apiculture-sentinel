# 🐝 Apiculture Sentinel

> AI-powered hive monitoring system for commercial apiaries — built with Google ADK and Streamlit.

Apiculture Sentinel continuously evaluates acoustic, environmental, and weight telemetry from IoT-connected beehives to detect anomalies, publish alerts, and surface actionable triage decisions through an interactive Fleet Command dashboard.

---

## Project Structure

```
apiculture/
├── agent/                         # Core ADK agent
│   ├── agent.py                   # ADK agent definition and MCP toolset binding
│   ├── fast_api_app.py            # ADK FastAPI server (SSE + /feedback + /run routes)
│   ├── app_utils/
│   │   ├── telemetry.py           # OpenTelemetry + Cloud Trace setup
│   │   └── typing.py              # Pydantic schemas (Feedback, etc.)
│   └── skills/
│       ├── state_evaluator.py     # Core hive-state evaluation engine (schema-driven)
│       ├── sentinel_memory.py     # In-session observation memory for temporal reasoning
│       ├── weather_provider.py    # MCP weather context provider
│       ├── spatial_manager.py     # Apiary spatial compliance validator
│       └── pubsub_alerter.py      # Google Cloud Pub/Sub alert publisher
│
├── frontend/                      # Streamlit multi-page dashboard
│   ├── app.py                     # Navigation entrypoint (st.navigation)
│   ├── home_landing.py            # Home page — fleet KPI overview & site cards
│   ├── database.py                # SQLite helpers (fleet.db queries & mutations)
│   ├── mcp_client.py              # MCP client initialisation & context fetching
│   └── pages/
│       ├── fleet_command.py       # Fleet Dashboard — triage queue & active alerts
│       └── hive_triage.py         # Node Triage — single-hive diagnostic workbench
│
├── servers/
│   └── mcp_server.py              # Local MCP server (weather & sensor simulation)
│
├── simulated_data/
│   ├── fleet.db                   # SQLite persistence (hive_fleet + diagnostic_events)
│   ├── telemetry_schema.json      # State-machine definitions & signal thresholds
│   ├── temperature_thresholds.json
│   └── weather_state.json         # Live-updated simulated weather context
│
├── tests/
│   ├── unit/                      # Unit tests (state evaluator, spatial manager)
│   └── integration/               # E2E server tests (FastAPI endpoints)
│
├── main.py                        # Standalone FastAPI REST API (ingest / run / feedback)
├── specs/                         # Architecture and API specifications
├── GEMINI.md                      # AI-assisted development guide
└── pyproject.toml                 # Project dependencies
```

---

## Requirements

Before you begin, ensure you have:

- **uv** — Python package manager ([Install](https://docs.astral.sh/uv/getting-started/installation/))
- **agents-cli** — `uv tool install google-agents-cli`
- **Google Cloud SDK** — For Pub/Sub, Cloud Logging, and Cloud Trace ([Install](https://cloud.google.com/sdk/docs/install))

---

## Quick Start

### 1. Install dependencies

```bash
agents-cli install
```

### 2. Run the Streamlit dashboard

```bash
uv run streamlit run frontend/app.py
```

The dashboard opens at **http://localhost:8501** with three views:
- **Home** — Fleet-wide KPI summary, site health cards, and quick navigation
- **Fleet Dashboard** — Live triage queue, anomaly charts, and active critical alerts
- **Node Triage** — Single-hive diagnostic workbench with AI evaluation and Human-in-the-Loop review

### 3. Run the REST API server

```bash
uv run uvicorn main:app --reload
```

API available at **http://localhost:8000** | Docs at `/docs`.

### 4. Run the ADK agent server

```bash
agents-cli playground
```

---

## REST API Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/api/v1/telemetry/ingest` | Accept IoT hive telemetry; triggers async state evaluation |
| `POST` | `/api/v1/run` | Synchronous evaluation — returns flat JSON decision |
| `POST` | `/api/v1/feedback` | Submit beekeeper Human-in-the-Loop feedback (`rating`, `comment`) |

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Schema-driven state machine** | `telemetry_schema.json` defines all hive states, signal thresholds, and persistence requirements — no hard-coded logic |
| **Temporal persistence reasoning** | `SentinelMemory` tracks in-session observations; states like `PEST_DISTRESS_VARROA` require 24 h of signal persistence before triggering |
| **MCP weather integration** | Environmental context is fetched from a local MCP server and injected into each evaluation |
| **Pub/Sub alerting** | Critical and warning states are published to Google Cloud Pub/Sub for downstream notification pipelines |
| **SQLite persistence** | All evaluations are written to `fleet.db` (`hive_fleet` + `diagnostic_events` tables) |
| **Human-in-the-Loop review** | Beekeepers can rate agent decisions (1–5) and add qualitative notes; feedback is `POST`ed to `/api/v1/feedback` |
| **Spatial compliance** | `ApiarySpatialManager` validates hive placement rules (clearance, regulations) independently from the triage flow |

---

## Detected Hive States

| State | Severity | Description |
|-------|----------|-------------|
| `NORMAL_HEALTHY` | LOW | Nominal acoustic and thermal readings |
| `COLD_STRESS_ALERT` | HIGH | Internal temp 20–31.9 °C |
| `HEAT_STRESS_ALERT` | HIGH | Internal temp 37–39.9 °C |
| `CRITICAL_HEAT_ALERT` | CRITICAL | Internal temp ≥ 40 °C |
| `PEST_DISTRESS_VARROA` | MEDIUM | Erratic mite-stress acoustics sustained 24 h |
| `PRE_SWARMING_ALERT` | HIGH | Piping acoustic signature detected |
| `SWARM_DEPARTURE_DETECTED` | CRITICAL | Weight loss + quiescent acoustics sustained 6 h |
| `CATASTROPHIC_MASS_LOSS` | CRITICAL | Non-biological weight drop > 5.1 kg/h |
| `QUEENLESS_COLONY` | CRITICAL | Mourning-roar acoustics sustained 12 h |

---

## Development Commands

| Command | Purpose |
|---------|---------|
| `uv run pytest tests/unit tests/integration` | Run all tests |
| `uv run pytest tests/unit/test_state_evaluator.py` | Run state evaluator unit tests |
| `agents-cli lint` | Run code quality checks |
| `agents-cli eval generate` | Run agent on eval dataset |
| `agents-cli eval grade` | Score evaluation traces |
| `agents-cli playground` | Launch ADK agent dev server |

---

## Deployment

```bash
gcloud config set project <your-project-id>
agents-cli deploy
```

To add CI/CD and Terraform infrastructure:

```bash
agents-cli scaffold enhance
agents-cli infra cicd
```

---

## Observability

Built-in telemetry exports to **Cloud Trace** and **Cloud Logging** via OpenTelemetry. Set `LOGS_BUCKET_NAME` to enable GCS artifact storage for ADK traces.

> 💡 Use [Gemini CLI](https://github.com/google-gemini/gemini-cli) for AI-assisted development — project context is pre-configured in `GEMINI.md`.
