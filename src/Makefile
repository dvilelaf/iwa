.PHONY: reset-tenderly
reset-tenderly:
	uv run iwa/tools/reset_tenderly.py


.PHONY: format
format:
	uv run ruff format && \
	uv run ruff check . --fix


.PHONY: publish
publish:
	uv build && \
	uv run twine upload dist/*