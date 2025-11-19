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


.PHONY: gemini
gemini:
	npx https://github.com/google-gemini/gemini-cli


.PHONY: test
test:
	uv run pytest --cov=src/iwa --cov-report=term-missing src/tests