CODESTYLE ?= codestyle
# Vendored controller snapshots under tests/fixtures/ are not ours to lint.
PYTHON_FILES := $(shell WB_PYTHON_FILES_EXCLUDE=tests/fixtures/ $(CODESTYLE)/python/ci/find-python-files)

.PHONY: fmt lint test cov clean registry

fmt:
	python3 -m black --config $(CODESTYLE)/python/config/pyproject.toml $(PYTHON_FILES)
	python3 -m isort --settings-file $(CODESTYLE)/python/config/pyproject.toml $(PYTHON_FILES)

lint:
	python3 -m black --config $(CODESTYLE)/python/config/pyproject.toml --check --diff $(PYTHON_FILES)
	python3 -m isort --settings-file $(CODESTYLE)/python/config/pyproject.toml --check --diff $(PYTHON_FILES)
	python3 -m pylint --rcfile $(CODESTYLE)/python/config/pyproject.toml $(PYTHON_FILES)

test:
	pytest

cov:
	pytest --cov --cov-config=$(CODESTYLE)/python/config/.coveragerc --cov-report=term --cov-fail-under=70

registry:
	python3 -m wb_cli._gen_registry
	python3 -m black --config $(CODESTYLE)/python/config/pyproject.toml --quiet wb_cli/_registry.py

clean:
	rm -rf build dist .coverage .pytest_cache htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name '*.egg-info' -exec rm -rf {} +
