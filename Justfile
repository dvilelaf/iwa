set shell := ["bash", "-uc"]

# Install dependencies
install:
    uv sync

# Run the dev environment
dev:
    PYTHONPATH=src uv run python -m iwa



# Reset everything (tenderly, config, wallet)
reset-all:
    PYTHONPATH=src uv run src/iwa/tools/reset_env.py

reset-tenderly:
    PYTHONPATH=src uv run src/iwa/tools/reset_env.py --keep-data

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
    uv run pip-audit --ignore-vuln CVE-2024-23342 --ignore-vuln CVE-2026-1703

# Type check
types:
    PYTHONNOUSERSITE=1 uv run mypy src/ --python-version 3.12

# Run tests
test:
    PYTHONPATH=src uv run pytest --cov=src/iwa --cov-report=term-missing src/

# Build package
build:
    uv build

# Publish to PyPI manually (normally done by GitHub Actions)
# Only use this for emergency manual releases
publish: build _validate-git-state _validate-tag-at-head
    #!/usr/bin/env bash
    set -e

    VERSION=$(grep -m1 'version = "' pyproject.toml | cut -d '"' -f 2)

    echo "⚠️  WARNING: Normally GitHub Actions publishes automatically when you push a tag."
    echo "   Only proceed if you need to publish manually for emergency reasons."
    read -p "Continue with manual publish? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Aborted"
        exit 1
    fi

    echo "📦 Publishing $VERSION to PyPI..."
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
web port="8080" host="0.0.0.0":
    -fuser -k {{port}}/tcp 2>/dev/null || true
    PYTHONPATH=src uv run python -m iwa.core.cli web --port {{port}} --host {{host}}

# List wallet backups
list-backups:
    @ls -la data/backup/*.bkp 2>/dev/null || echo "No backups found"

# Restore wallet from backup (use just list-backups to see available backups)
restore-wallet backup:
    PYTHONPATH=src uv run python src/iwa/tools/restore_backup.py {{backup}}

# Validate git state (uncommitted changes, lockfile sync, and branch pushability)
_validate-git-state:
    #!/usr/bin/env bash
    set -e

    # 1. Check for uncommitted changes
    if [ -n "$(git status --porcelain)" ]; then
        echo "❌ Error: Uncommitted changes found! Commit or stash them first."
        git status --short
        exit 1
    fi

    # 2. Verify uv.lock is in sync
    echo "🔍 Verifying uv.lock is up to date..."
    uv lock --locked || {
        echo "❌ Error: uv.lock is out of sync!"
        echo "   Run: uv lock && git add uv.lock && git commit -m 'build: Update lockfile'"
        exit 1
    }

    # 3. Check that local branch is in sync with remote
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    git fetch origin "$BRANCH" --quiet 2>/dev/null || {
        echo "⚠️  Warning: Could not fetch from origin (offline?). Skipping remote sync check."
        exit 0
    }
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")
    if [ -z "$REMOTE" ]; then
        echo "⚠️  Warning: No remote branch origin/$BRANCH found. Will be created on push."
    elif [ "$LOCAL" != "$REMOTE" ]; then
        # Check if local is simply ahead (normal) vs diverged (dangerous)
        if ! git merge-base --is-ancestor "$REMOTE" "$LOCAL"; then
            echo "❌ Error: Local $BRANCH has diverged from origin/$BRANCH!"
            echo "   Local:  $LOCAL"
            echo "   Remote: $REMOTE"
            echo "   This usually means you amended commits. Push or reset first."
            exit 1
        fi
    fi

# Validate that version tag exists and points to current HEAD
_validate-tag-at-head:
    #!/usr/bin/env bash
    set -e

    VERSION=$(grep -m1 'version = "' pyproject.toml | cut -d '"' -f 2)
    TAG="v$VERSION"

    if ! git rev-parse "$TAG" >/dev/null 2>&1; then
        echo "❌ Error: Tag $TAG does not exist!"
        echo "   Create it with: git tag -a $TAG -m 'Release $TAG' && git push origin $TAG"
        exit 1
    fi

    TAG_COMMIT=$(git rev-parse "$TAG")
    HEAD_COMMIT=$(git rev-parse HEAD)
    if [ "$TAG_COMMIT" != "$HEAD_COMMIT" ]; then
        echo "❌ Error: Tag $TAG does not point to current HEAD!"
        echo "   Tag points to: $TAG_COMMIT"
        echo "   HEAD is at:    $HEAD_COMMIT"
        echo "   Delete and recreate the tag: git tag -d $TAG && git push origin :refs/tags/$TAG"
        echo "   Then: git tag -a $TAG -m 'Release $TAG' && git push origin $TAG"
        exit 1
    fi

# Run full release quality gate (Security -> Lint -> Test -> Build -> Git validations)
release-check: _validate-git-state
    #!/usr/bin/env bash
    set -e

    VERSION=$(grep -m1 'version = "' pyproject.toml | cut -d '"' -f 2)
    TAG="v$VERSION"

    # Fail fast: check tag doesn't already exist before running quality gates
    if git rev-parse "$TAG" >/dev/null 2>&1; then
        echo "❌ Error: Tag $TAG already exists!"
        echo "   If you need to recreate it: git tag -d $TAG && git push origin :refs/tags/$TAG"
        exit 1
    fi

    echo "🛡️  Running Security Checks..."
    just security
    echo "🧹 Running Linters..."
    just check
    echo "🧪 Running Tests..."
    just test
    echo "📦 Building Package..."
    just build

    echo "✅ All checks passed! Ready to release $TAG."

# Create and push release tag (run release-check first)
release: release-check
    #!/usr/bin/env bash
    set -e

    VERSION=$(grep -m1 'version = "' pyproject.toml | cut -d '"' -f 2)
    TAG="v$VERSION"

    echo "🚀 Creating and pushing tag $TAG..."
    git tag -a "$TAG" -m "Release $TAG"
    git push origin main
    git push origin "$TAG"
    echo "✅ Release $TAG created and pushed!"
# List contracts status (sort options: name, rewards, epoch, slots, olas)
contracts sort="name":
    PYTHONPATH=src uv run src/iwa/tools/list_contracts.py --sort {{sort}}

# Check wallet integrity (accounts and mnemonic)
wallet-check:
    uv run iwa-wallet-check
