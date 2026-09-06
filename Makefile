.PHONY: help install dev test test-acceptance \
	certify reconcile rollback fire-drill operator-readiness phase7-tests \
	demo-seed demo-preflight demo-up demo-down demo-certify demo-reset \
	demo-golden-prepare demo-golden-apply

help:
	@echo "Commands: make dev, make test, make test-acceptance,"
	@echo "          make certify, make reconcile, make rollback, make fire-drill,"
	@echo "          make operator-readiness,"
	@echo "          make demo-seed, make demo-preflight, make demo-up,"
	@echo "          make demo-certify, make demo-down, make demo-reset,"
	@echo "          make demo-golden-prepare, make demo-golden-apply PROPOSAL_ID=<id>"

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

# --- Post-deploy operator readiness -----------------------------------------
operator-readiness:
	PYTHONPATH=. python3 scripts/operator_readiness.py

# --- Certified demo installation -------------------------------------------
DEMO_ENV ?= .env.demo
DEMO_COMPOSE = docker compose --env-file $(DEMO_ENV) -f compose.yml -f compose.demo.yml
GOLDEN_PREPARED ?= .dor-demo/golden-run-prepared.json
GOLDEN_GOVERNED ?= .dor-demo/golden-run-governed.json
GOLDEN_ACCEPTANCE ?= .dor-demo/golden-run-acceptance.json
GOLDEN_FINAL ?= .dor-demo/golden-run-final.json

demo-seed:
	PYTHONPATH=. python3 scripts/demo_installation.py seed --env-file $(DEMO_ENV)

demo-preflight:
	PYTHONPATH=. python3 scripts/demo_installation.py preflight --env-file $(DEMO_ENV)

demo-up: demo-preflight
	$(DEMO_COMPOSE) up -d --build

demo-down:
	$(DEMO_COMPOSE) down --remove-orphans

demo-certify:
	PYTHONPATH=. python3 scripts/demo_installation.py certify --env-file $(DEMO_ENV)

demo-reset:
	PYTHONPATH=. python3 scripts/demo_installation.py reset --env-file $(DEMO_ENV)

# --- Golden Real Run v1 -----------------------------------------------------
demo-golden-prepare: demo-certify
	@mkdir -p .dor-demo
	@rm -f $(GOLDEN_PREPARED) $(GOLDEN_GOVERNED) $(GOLDEN_ACCEPTANCE) $(GOLDEN_FINAL)
	@$(DEMO_COMPOSE) exec -T dashboard python scripts/golden_run.py prepare > $(GOLDEN_PREPARED)
	@PYTHONPATH=. python3 scripts/golden_run.py review --input $(GOLDEN_PREPARED)

demo-golden-apply:
	@test -n "$(PROPOSAL_ID)" || (echo "PROPOSAL_ID is required" >&2; exit 2)
	@test -f $(GOLDEN_PREPARED) || (echo "Run make demo-golden-prepare first" >&2; exit 2)
	@cat $(GOLDEN_PREPARED) | $(DEMO_COMPOSE) exec -T dashboard python scripts/golden_run.py apply --input - --proposal-id "$(PROPOSAL_ID)" > $(GOLDEN_GOVERNED)
	@$(DEMO_COMPOSE) exec -T api python scripts/golden_run.py acceptance > $(GOLDEN_ACCEPTANCE)
	@PYTHONPATH=. python3 scripts/golden_run.py finalize --governed $(GOLDEN_GOVERNED) --acceptance $(GOLDEN_ACCEPTANCE) > $(GOLDEN_FINAL)
	@PYTHONPATH=. python3 scripts/golden_run.py review-final --input $(GOLDEN_FINAL)
	@echo "Golden evidence: $(GOLDEN_FINAL)"
