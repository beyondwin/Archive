PYTHON ?= .venv/bin/python

.PHONY: install test build wheel clean

install:
	$(PYTHON) -m pip --version >/dev/null 2>&1 || $(PYTHON) -m ensurepip --upgrade
	$(PYTHON) -m pip install -e .[test]
	cd web && npm ci

test:
	$(PYTHON) -m pytest -q
	cd web && npx vitest run && npx playwright test

build:
	cd web && npm run build

wheel: build
	rm -rf dist build src/*.egg-info *.egg-info
	$(PYTHON) -m pip --version >/dev/null 2>&1 || $(PYTHON) -m ensurepip --upgrade
	$(PYTHON) -m pip install build
	$(PYTHON) -m build --wheel

clean:
	rm -rf web/node_modules web/.vite web/dist
	find src/agentlens/web_assets -mindepth 1 ! -name __init__.py -exec rm -rf {} +
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf dist build src/*.egg-info *.egg-info
