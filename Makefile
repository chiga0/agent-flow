.PHONY: local-init local-doctor local-up local-status local-smoke local-demo local-load local-logs local-down

local-init:
	python3 scripts/local_stack.py init

local-doctor:
	python3 scripts/local_stack.py doctor

local-up:
	python3 scripts/local_stack.py up

local-status:
	python3 scripts/local_stack.py status

local-smoke:
	python3 scripts/local_stack.py smoke

local-demo:
	python3 scripts/local_stack.py demo

local-load:
	python3 scripts/validate_ha_load.py --token "$${RUN_MANAGER_TOKEN:?set RUN_MANAGER_TOKEN}"

local-logs:
	python3 scripts/local_stack.py logs

local-down:
	python3 scripts/local_stack.py down
