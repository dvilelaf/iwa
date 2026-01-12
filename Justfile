set shell := ["bash", "-uc"]

# Install dependencies
install:
    uv sync

# Run the dev environment
dev:
    PYTHONPATH=src uv run python -m iwa

# Reset tenderly
reset-tenderly profile="1":
    PYTHONPATH=src uv run src/iwa/tools/reset_tenderly.py --profile {{profile}}

# Reset everything (tenderly, config, wallet)
reset-all:
    PYTHONPATH=src uv run src/iwa/tools/reset_env.py

# Check active tenderly profile
check-tenderly-profile:
    PYTHONPATH=src uv run src/iwa/tools/check_profile.py

# Format code
format:
    uv run ruff format src/
    uv run ruff check src/ --fix
    uv run djlint src/ --reformat
    npx -y prettier 'src/**/*.{js,css}' --write

# Check code (lint only)
check: types
    uv run ruff check src/
    uv run djlint src/ --check
    npx -y prettier 'src/**/*.{js,css}' --check
    uv run python scripts/lint_js_html.py

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
    PYTHONPATH=src uv run pytest --cov=src/iwa --cov-report=term-missing src/

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
    PYTHONPATH=src uv run python -m iwa.core.cli web --port {{port}} --host {{host}}

# List wallet backups
list-backups:
    @ls -la data/backup/*.bkp 2>/dev/null || echo "No backups found"

# Restore wallet from backup (use just list-backups to see available backups)
restore-wallet backup:
    PYTHONPATH=src uv run python src/iwa/tools/restore_backup.py {{backup}}

# Run full release quality gate locally (Security -> Lint -> Test -> Build)
release-check:
    @echo "🛡️  Running Security Checks..."
    @just security
    @echo "🧹 Running Linters..."
    @just check
    @echo "🧪 Running Tests..."
    @just test
    @echo "📦 Building Package..."
    @just build
    @echo "✅ All checks passed! Ready for release."

# Create a new release (tag and push) - triggers GitHub Actions
release version:

# List contracts status
contracts:
    PYTHONPATH=src uv run src/iwa/tools/list_contracts.py
