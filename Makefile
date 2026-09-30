# VASP-FUSION. Every number printed by these targets regenerates from source data.
PY      := $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python)
PORT    ?= 8000
RESEARCH ?= ../research/data

.PHONY: help setup labels test serve mocks openapi types offline-check clean

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t18

setup:            ## create the venv and install everything (needs network ONCE)
	uv venv --python 3.12
	uv pip install -e ".[dev]"

labels:           ## build data/labels.duckdb from the research label CSVs, print stats
	$(PY) -m vaspfusion.cli labels --research $(RESEARCH) --db data/labels.duckdb

test:             ## unit + integration tests
	$(PY) -m pytest -q

serve:            ## run the API on :$(PORT)
	$(PY) -m vaspfusion.cli serve --port $(PORT)

mocks:            ## regenerate mocks/*.json (seeded, validated against the schemas)
	$(PY) scripts/make_mocks.py

openapi:          ## write docs/openapi.json from the FastAPI app
	$(PY) -m vaspfusion.cli openapi --out docs/openapi.json

types: openapi    ## generate ui/src/api/types.ts from the OpenAPI schema
	cd ui && npx --yes openapi-typescript@7.13.0 ../docs/openapi.json -o src/api/types.ts

offline-check:    ## fail if any source file reaches the network at runtime
	@! grep -rnE "https?://" --include=*.py vaspfusion/ \
		| grep -vE "#|\"\"\"|docs|example\.com|source_url|SOURCE_URL" \
		|| (echo "FAIL: a runtime URL is present" && exit 1)
	@echo "PASS: no outbound endpoints in application code."

clean:
	rm -rf data/labels.duckdb data/case.duckdb ui/dist
