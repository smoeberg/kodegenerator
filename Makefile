.PHONY: help install dev test test-acceptance 	certify reconcile rollback fire-drill phase7-tests

help:
	@echo "Commands: make dev, make test, make test-acceptance,"
	@echo "          make certify, make reconcile, make rollback, make fire-drill"

dev:
	pip install -r requirements.txt

test:
	pytest -v

test-acceptance:
	pytest tests/acceptance/test_real_system.py -v

# --- Fase 7 ----------------------------------------------------------------
phase7-tests:
	pytest tests/test_platform_skip_manifest.py tests/test_release_candidate.py tests/sdk/test_proxy_matrix.py -q

# --- Fase 8 staging certification & reconciliation --------------------------
LEDGER ?= ci/staging/ledger.json
REPO   ?= smoeberg/kodegenerator
IMAGE  ?= ghcr.io/smoeberg/kodegenerator

certify:
	PYTHONPATH=. python3 ci/staging/reconcile_cli.py certify \
		--ledger $(LEDGER) --repo $(REPO) --image $(IMAGE) \
		--digest $(DIGEST) --gate-run $(GATE_RUN)

reconcile:
	PYTHONPATH=. python3 ci/staging/reconcile_cli.py status \
		--ledger $(LEDGER) --repo $(REPO) --image $(IMAGE) \
		--digest $(DIGEST) $(if $(DEPLOY_STATE),--deployment-state $(DEPLOY_STATE),)

rollback:
	PYTHONPATH=. python3 ci/staging/reconcile_cli.py rollback \
		--ledger $(LEDGER) --repo $(REPO) --image $(IMAGE) $(if $(DIGEST),--digest $(DIGEST),)

fire-drill:
	bash scripts/fire_drill.sh
