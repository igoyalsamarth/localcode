.PHONY: help install dev-infra dev-up dev-down docker-up docker-down docker-logs scale-workers test test-cov test-unit test-watch clean

help:
	@echo "LocalCode - Microservices Commands"
	@echo ""
	@echo "Development:"
	@echo "  make install       - Install dependencies"
	@echo "  make dev-infra     - Start RabbitMQ and PostgreSQL"
	@echo "  make dev-up        - Start all services locally (3 terminals needed)"
	@echo "  make dev-down      - Stop infrastructure"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up     - Start all services with Docker Compose"
	@echo "  make docker-down   - Stop all Docker services"
	@echo "  make docker-logs   - View logs from all services"
	@echo "  make scale-workers - Scale workers to 5 instances"
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run all tests"
	@echo "  make test-cov      - Run tests with coverage report"
	@echo "  make test-unit     - Run only unit tests"
	@echo "  make test-watch    - Run tests in watch mode"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean         - Clean up caches and temp files"

install:
	uv sync

dev-infra:
	@echo "Starting RabbitMQ..."
	docker run -d --name localcode-rabbitmq \
		-p 5672:5672 \
		-p 15672:15672 \
		rabbitmq:3.13-management-alpine || true
	@echo ""
	@echo "Infrastructure started!"
	@echo "RabbitMQ UI: http://localhost:15672 (guest/guest)"
	@echo ""
	@echo "Note: Using cloud-hosted PostgreSQL from .env"

dev-down:
	@echo "Stopping infrastructure..."
	docker stop localcode-rabbitmq || true
	docker rm localcode-rabbitmq || true

dev-up:
	@echo "Start these in separate terminals:"
	@echo ""
	@echo "Terminal 1: ./run_api_backend.sh (includes webhooks)"
	@echo "Terminal 2: ./run_worker.sh"

docker-up:
	docker-compose up -d
	@echo ""
	@echo "Services started!"
	@echo "API Backend (with webhooks): http://localhost:8000"
	@echo "RabbitMQ UI: http://localhost:15672"
	@echo ""
	@echo "Note: Using cloud-hosted PostgreSQL from .env"

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

scale-workers:
	docker-compose up -d --scale worker=5
	@echo "Scaled to 5 worker instances"

test:
	pytest

test-cov:
	pytest --cov=. --cov-report=html --cov-report=term-missing

test-unit:
	pytest -m unit

test-watch:
	pytest --watch

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf htmlcov
	rm -rf workspace
	@echo "Cleaned up caches and temp files"
