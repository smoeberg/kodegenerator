.PHONY: help install dev test test-acceptance

help:
	@echo "Commands: make dev, make test, make test-acceptance"

dev:
	pip install -r requirements.txt

test:
	pytest -v

test-acceptance:
	pytest tests/acceptance/test_real_system.py -v
