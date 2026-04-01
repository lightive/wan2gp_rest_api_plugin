.PHONY: install test lint format check clean

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -v --tb=short

lint:
	ruff check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy .

check: lint typecheck test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache/ .mypy_cache/ .ruff_cache/ dist/ build/
