.PHONY: install run test smoke demo clean

install:
	pip install -r requirements.txt

run:
	uvicorn app.main:app --reload

test:
	pytest

smoke:
	python scripts/smoke_test.py

# needs the server running in another shell
demo:
	python scripts/e2e_demo.py

clean:
	rm -f ct200.db data/generations.jsonl
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
