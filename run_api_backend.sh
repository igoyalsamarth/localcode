#!/bin/bash
# Run Service 1: API Backend
# Main API for user authentication, onboarding, and agent management
# Runs on port 8000

set -e

echo "Starting LocalCode API Backend..."
uv run api-backend
