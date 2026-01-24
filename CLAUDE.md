# iwa

Secure crypto wallet framework with plugin-based protocol integrations.

## Directories

| Path | What | When to read |
|------|------|--------------|
| `src/iwa/` | Main Python package | Implementing features, debugging issues |
| `docs/` | MkDocs documentation source | Writing user docs, understanding features |
| `scripts/` | Build/lint helper scripts | Modifying build process, adding checks |
| `.github/` | GitHub Actions CI workflows | Changing CI/CD pipeline |

## Files

| File | What | When to read |
|------|------|--------------|
| `README.md` | Project overview, setup, usage | Getting started, understanding architecture |
| `pyproject.toml` | Package config, dependencies, tool settings | Adding deps, changing build config |
| `Justfile` | Task runner commands | Running dev tasks, adding automation |
| `Dockerfile` | Container build definition | Modifying Docker deployment |
| `docker-compose.yml` | Multi-container orchestration | Changing container setup |
| `mkdocs.yml` | Documentation site config | Configuring docs site |
| `.gitignore` | Git ignore patterns | Adding exclusions |
| `.eslintrc.json` | JS/TS lint config | Changing JS lint rules |
| `.gitleaksignore` | Secret scanning exclusions | Allowing known false positives |

## Commands

```bash
# Development
just install        # Install dependencies
just dev            # Run dev environment
just tui            # Launch TUI
just web            # Launch Web API

# Quality
just format         # Format code
just check          # Lint code
just types          # Type check
just test           # Run tests
just security       # Security checks

# Build & Release
just build          # Build package
just publish        # Publish to PyPI
just docker-build   # Build container
just release-check  # Full release gate
```
