# Release Workflow

Iwa uses a fully automated CI/CD pipeline built on **GitHub Actions** to ensure quality and streamline releases.

## Workflow Overview

The release process is triggered by git tags.

### Trigger
```bash
git tag v0.1.0
git push --tags
```

### Steps

1. **Quality Gate (Job 1)**:
   - **Secrets Check**: `gitleaks` scans for secret keys.
   - **Security Audit**: `bandit` and `pip-audit` check code and dependencies.
   - **Linting**: `ruff`, `djlint`, `prettier` ensure code style.
   - **Testing**: `pytest` runs the full test suite.
   - *If any of these fail, the release is aborted.*

2. **Publish (Job 2)**:
   - **Auto-Versioning**: The `version` in `pyproject.toml` is automatically updated to match the git tag (e.g., `v0.1.0` -> `0.1.0`).
   - **GitHub Release**: A release is created on GitHub with the wheel file attached.
   - **PyPI**: The package is published to PyPI.
   - **DockerHub**: The docker image is pushed to `dvilela/iwa`.

## Secrets Configuration

To enable this workflow, the following secrets must be set in the repository:

| Secret | Description |
|--------|-------------|
| `PYPI_TOKEN` | API Token for PyPI upload (Scope: Entire account) |
| `DOCKERHUB_USERNAME` | DockerHub username (e.g., `dvilela`) |
| `DOCKERHUB_TOKEN` | DockerHub Access Token |
