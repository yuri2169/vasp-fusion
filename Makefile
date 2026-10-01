# VASP-FUSION. Every number printed by these targets regenerates from source data.
PY      := $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python)
PORT    ?= 8000
RESEARCH ?= ../research/data

.PHONY: help setup labels discover discover-run discover-eval model-data model test serve fetch trace demo mocks openapi types offline-check clean

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t18

setup:            ## create the venv and install everything (needs network ONCE)
	uv venv --python 3.12
	uv pip install -e ".[dev]"

labels:           ## build data/labels.duckdb from the research label CSVs + derived/, print stats
	$(PY) -m vaspfusion.cli labels --research "$(RESEARCH)" --db data/labels.duckdb

discover:         ## derive Tron deposit addresses into derived/ (cached; OFFLINE=1 replays), then `make labels`
	$(PY) -m vaspfusion.cli discover --chain tron
	$(PY) -m vaspfusion.cli discover --chain tron --entities CoinDCX --since 2026-08-01 --name tron_coindcx_aug
	$(PY) -m vaspfusion.cli discover --chain tron --entities CoinDCX --since 2025-05-25 --name tron_coindcx_2025

discover-run:     ## one discovery run: ENTITIES="OKX,HTX" SINCE=2026-09-01 NAME=tron_sep
	$(PY) -m vaspfusion.cli discover --chain tron $(if $(ENTITIES),--entities "$(ENTITIES)") \
		$(if $(SINCE),--since $(SINCE)) $(if $(NAME),--name $(NAME))

discover-eval:    ## measure the discovery rules on held-out explorer-tagged deposit addresses
	$(PY) -m vaspfusion.cli discover-eval

MODEL_CHAIN ?= tron
model-data:       ## build the deposit model's training set into artifacts/model_v1/$(MODEL_CHAIN)/ (cached; OFFLINE=1 replays)
	$(PY) -m vaspfusion.cli model-data --chain $(MODEL_CHAIN)

model:            ## train, calibrate and measure the deposit model on that set; score the derived labels, then `make labels`
	$(PY) -m vaspfusion.cli model --chain $(MODEL_CHAIN)

test:             ## unit + integration tests
	$(PY) -m pytest -q

serve:            ## run the API on :$(PORT)
	$(PY) -m vaspfusion.cli serve --port $(PORT)

fetch:            ## transfers for ADDR=<address> [CHAIN=..] (cached; OFFLINE=1 = cache only)
	$(PY) -m vaspfusion.cli fetch "$(ADDR)" $(if $(CHAIN),--chain $(CHAIN))

trace:            ## trace ADDR=<address> [CHAIN=..] [HOPS=3] to its nearest exchange(s)
	$(PY) -m vaspfusion.cli trace "$(ADDR)" $(if $(CHAIN),--chain $(CHAIN)) $(if $(HOPS),--max-hops $(HOPS))

demo:             ## run the demo wallets (demo/cases.json) into the case store; OFFLINE=1 replays
	$(PY) -m vaspfusion.cli demo

mocks:            ## regenerate mocks/*.json (seeded, validated against the schemas)
	$(PY) scripts/make_mocks.py

openapi:          ## write docs/openapi.json from the FastAPI app
	$(PY) -m vaspfusion.cli openapi --out docs/openapi.json

types: openapi    ## generate ui/src/api/types.ts from the OpenAPI schema
	cd ui && npx --yes openapi-typescript@7.13.0 ../docs/openapi.json -o src/api/types.ts

offline-check:    ## fail if code outside vaspfusion/chains/ can reach the network
	@! grep -rnE "https?://" --include=*.py --exclude-dir=chains vaspfusion/ \
		| grep -vE "#|\"\"\"|docs|example\.com|source_url|SOURCE_URL" \
		|| (echo "FAIL: a runtime URL is present outside vaspfusion/chains/" && exit 1)
	@! grep -rnE "^\s*(import|from) (urllib\.request|http\.client|socket|requests|httpx)" \
		--include=*.py --exclude=http.py vaspfusion/ \
		|| (echo "FAIL: only vaspfusion/chains/http.py may open sockets" && exit 1)
	@echo "PASS: the only outbound code is vaspfusion/chains/ (chain APIs), and OFFLINE=1 serves it from the cache."

clean:
	rm -rf data/labels.duckdb data/case.duckdb ui/dist
