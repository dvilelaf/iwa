.PHONY: reset-tenderly
reset-tenderly:
	uv run iwa/tools/reset_tenderly.py


.PHONY: format
format:
	uv run ruff format


.PHONY: lint
lint:
	uv run ruff check

.PHONY: publish
publish:
	uv build
	uv run twine upload dist/*