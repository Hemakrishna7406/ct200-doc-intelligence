.PHONY: install install-dev run test cov lint fmt check smoke demo docker clean

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

run:
	uvicorn app.main:app --reload

test:
	pytest

cov:
	pytest --cov=app --cov-report=term-missing

lint:
	ruff check app tests scripts

fmt:
	ruff check --fix app tests scripts
	ruff format app tests scripts

# what CI runs
check: lint test

smoke:
	python scripts/smoke_test.py

# needs the server running in another shell
demo:
	python scripts/e2e_demo.py

docker:
	docker build -t ct200-doc-intelligence .

clean:
	rm -f ct200.db data/generations.jsonl
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
