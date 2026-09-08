.PHONY: help install dev test lint format security docs build deploy clean

# Variables
PYTHON := python3
PIP := $(PYTHON) -m pip
VENV := venv

help:
	@echo "Pve-Bot Development Commands"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make install          Install dependencies"
	@echo "  make dev             Install dev dependencies"
	@echo "  make venv            Create virtual environment"
	@echo ""
	@echo "Development:"
	@echo "  make run             Run bot locally"
	@echo "  make run-docker      Run bot in Docker"
	@echo "  make test            Run tests"
	@echo "  make test-cov        Run tests with coverage"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint            Run linting checks"
	@echo "  make format          Auto-format code"
	@echo "  make security        Run security scan"
	@echo "  make quality         Run all quality checks"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs            Generate documentation"
	@echo ""
	@echo "Deployment:"
	@echo "  make build           Build Docker image"
	@echo "  make docker-up       Start Docker services"
	@echo "  make docker-down     Stop Docker services"
	@echo ""
	@echo "Maintenance:"
	@echo "  make clean           Remove build artifacts"
	@echo "  make backup          Backup data"
	@echo "  make validate        Validate data integrity"

# Setup
venv:
	$(PYTHON) -m venv $(VENV)
	. $(VENV)/bin/activate && $(PIP) install --upgrade pip

install: venv
	. $(VENV)/bin/activate && $(PIP) install -r requirements.txt

dev: install
	. $(VENV)/bin/activate && $(PIP) install -r requirements-dev.txt
	. $(VENV)/bin/activate && pre-commit install

# Development
run:
	. $(VENV)/bin/activate && $(PYTHON) vouch_bot.py

run-docker:
	docker-compose up

# Testing
test:
	. $(VENV)/bin/activate && pytest tests/ -v

test-cov:
	. $(VENV)/bin/activate && pytest tests/ -v --cov=. --cov-report=html --cov-report=term

# Code Quality
lint:
	. $(VENV)/bin/activate && flake8 . --max-line-length=120
	. $(VENV)/bin/activate && pylint vouch_bot.py dashboard.py data_store.py || true

format:
	. $(VENV)/bin/activate && black .
	. $(VENV)/bin/activate && isort .

security:
	. $(VENV)/bin/activate && bandit -r . -ll

quality: lint security test
	@echo "✓ All quality checks passed"

# Documentation
docs:
	. $(VENV)/bin/activate && mkdocs build
	@echo "Documentation built in site/"

# Docker
build:
	docker build -t pve-bot:latest .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f pve-bot

# Maintenance
backup:
	./maintenance.sh backup

validate:
	./maintenance.sh validate

health:
	./maintenance.sh health

audit:
	./maintenance.sh audit

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type d -name ".coverage" -exec rm -rf {} +
	find . -type d -name "dist" -exec rm -rf {} +
	find . -type d -name "build" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +

# Full cleanup
clean-all: clean
	rm -rf $(VENV)
	rm -rf .pytest_cache
	rm -rf .mypy_cache
	rm -rf site/

.DEFAULT_GOAL := help
