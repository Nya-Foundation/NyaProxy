# NyaProxy developer tasks.
# Run `make` or `make help` to see available targets.

.DEFAULT_GOAL := help
.PHONY: help install test test-unit test-e2e coverage lint typecheck format clean build

PYTHON ?= python

help:  ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install the package with dev dependencies
	$(PYTHON) -m pip install -e ".[dev,lint]"

test:  ## Run the full test suite
	$(PYTHON) -m pytest

test-unit:  ## Run unit tests only
	$(PYTHON) -m pytest tests/unit

test-e2e:  ## Run end-to-end tests only
	$(PYTHON) -m pytest tests/e2e -m e2e

coverage:  ## Run tests and write an HTML coverage report to reports/htmlcov
	$(PYTHON) -m pytest --cov-report=html
	@echo "Coverage report: reports/htmlcov/index.html"

lint:  ## Check formatting and import order without modifying files
	$(PYTHON) -m black --check .
	$(PYTHON) -m isort --check-only --profile black .

typecheck:  ## Run mypy on the type-clean module set (see pyproject [tool.mypy])
	$(PYTHON) -m mypy

format:  ## Auto-format code with black and isort
	$(PYTHON) -m isort --profile black .
	$(PYTHON) -m black .

clean:  ## Remove build artifacts, caches, and generated reports
	$(PYTHON) .clean.py

build:  ## Build the distributable package into dist/
	$(PYTHON) -m build
