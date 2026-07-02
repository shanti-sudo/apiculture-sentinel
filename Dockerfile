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

FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.8.13

# Create appuser system group and user using standard useradd commands
RUN groupadd -r appuser && useradd -r -g appuser -m -d /home/appuser -s /sbin/nologin appuser

WORKDIR /app

COPY ./pyproject.toml ./README.md ./uv.lock* ./

COPY . .

# Sync dependencies and ensure /app and its contents are owned by appuser
RUN uv sync --frozen && chown -R appuser:appuser /app

ARG COMMIT_SHA=""
ENV COMMIT_SHA=${COMMIT_SHA}

ARG AGENT_VERSION=0.0.0
ENV AGENT_VERSION=${AGENT_VERSION}

EXPOSE 8080

# Switch to non-root user
USER appuser

CMD ["uv", "run", "streamlit", "run", "frontend/app.py", "--server.port", "8080", "--server.address", "0.0.0.0"]