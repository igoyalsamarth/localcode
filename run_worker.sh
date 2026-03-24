#!/bin/bash
# Run Service 3: Worker
# Dramatiq worker that consumes tasks from RabbitMQ and executes the agent
# Can run multiple instances for horizontal scaling

set -e

echo "Starting LocalCode Worker..."
uv run worker
