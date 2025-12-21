set shell := ["bash", "-uc"]

# Install dependencies
install:
    uv sync

# Run the dev environment
dev:
    uv run python -m iwa

# Reset tenderly
reset-tenderly profile="1":
    uv run src/iwa/tools/reset_tenderly.py --profile {{profile}}

# Format code
format:
    uv run ruff format src/
    uv run ruff check src/ --fix

# Check code (lint only)
check:
    uv run ruff check src/

# Run security checks
security:
    # Check for secrets
    gitleaks detect --source . -v
    # Check for common security issues in code
    uv run bandit -c pyproject.toml -r src/
    # Check for vulnerable dependencies
    uv run pip-audit --ignore-vuln CVE-2024-23342

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

# Launch Web Server (kills any existing process on the port first)
web port="8080" host="127.0.0.1":
    -fuser -k {{port}}/tcp 2>/dev/null || true
    uv run iwa web --port {{port}} --host {{host}}
