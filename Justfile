set shell := ["bash", "-uc"]

# Install dependencies
install:
    uv sync

# Run the dev environment
dev:
    uv run python -m iwa

# Reset tenderly
reset-tenderly:
    uv run src/iwa/tools/reset_tenderly.py

# Format code
format:
    uv run ruff format src/
    uv run ruff check src/ --fix

# Check code (lint only)
check:
    uv run ruff check src/

# Type check
types:
    PYTHONNOUSERSITE=1 uv run mypy src/ --python-version 3.12

# Run tests
test:
    PYTHONPATH=src uv run pytest --cov=src --cov-report=term-missing src/

# Build package
build:
    uv build

# Publish to Pypi
publish: build
    uv run twine upload dist/*

# Docker build
docker-build:
    docker build -t iwa:latest .

# Docker run
docker-run:
    docker-compose up --build

# Push to Docker Hub
docker-push tag="latest":
    docker tag iwa:latest david/iwa:{{tag}}
    docker push david/iwa:{{tag}}

# Serve documentation
docs-serve:
    uv run mkdocs serve

# Build documentation
docs-build:
    uv run mkdocs build

# Launch TUI
tui:
    uv run iwa tui

# Launch Web Server
web port="8000" host="127.0.0.1":
    uv run iwa web --port {{port}} --host {{host}}
