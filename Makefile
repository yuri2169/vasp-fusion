# VASP-FUSION. Every number printed by these targets regenerates from source data.
PY      := $(if $(wildcard .venv/Scripts/python.exe),.venv/Scripts/python.exe,.venv/bin/python)
PORT    ?= 8000
RESEARCH ?= ../research/data

.PHONY: help setup labels tagpacks discover discover-run discover-eval model-data model abstain-eval test serve fetch trace demo demo-cache verify case-pdf audit desk letter mocks openapi types ui-setup ui-dev ui-test ui-build ui-shots offline-check reproduce docker docker-up docker-down docker-smoke clean

help:
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t18

setup:            ## create the venv and install everything (needs network ONCE)
	uv venv --python 3.12
	uv pip install -e ".[dev]"

labels:           ## build data/labels.duckdb from the research label CSVs + derived/, print stats
	$(PY) -m vaspfusion.cli labels --research "$(RESEARCH)" --db data/labels.duckdb

tagpacks:         ## flatten the GraphSense exchange TagPacks ($(RESEARCH)/graphsense-tagpacks/packs) into the CSV `make labels` reads
	$(PY) -m vaspfusion.cli tagpacks --packs "$(RESEARCH)/graphsense-tagpacks/packs" \
		--out "$(RESEARCH)/graphsense_tagpacks_exchange.csv"

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

abstain-eval:     ## measure the abstain threshold on label-hidden traces of real customers (cached; OFFLINE=1 replays)
	$(PY) -m vaspfusion.cli abstain-eval

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

demo-cache:       ## build data/demo_cache.duckdb from the recorded demo fixtures (no network; the image ships it)
	$(PY) -m vaspfusion.cli demo-cache

verify:           ## trace stored cases again from the cache only and compare fingerprints: CASE=<id>, or all
	$(PY) -m vaspfusion.cli verify $(if $(CASE),"$(CASE)",--all)

case-pdf:         ## the case file (A4 PDF) and receipt of CASE=<id> -> data/exports/
	$(PY) -m vaspfusion.cli case-pdf "$(CASE)"

audit:            ## check the audit log's hash chain (list it with `python -m vaspfusion.cli audit`)
	$(PY) -m vaspfusion.cli audit --verify

desk:             ## the request desk: which exchanges the finished cases route to (run `make demo` first)
	$(PY) -m vaspfusion.cli desk

OFFICER ?= Investigating Officer
letter:           ## draft one request: VASP=CoinDCX [OFFICER="Insp. A. Rao"] [CASES=a,b] [SEND=1] -> data/exports/<id>.pdf
	$(PY) -m vaspfusion.cli request "$(VASP)" --officer "$(OFFICER)" \
		$(if $(CASES),--cases "$(CASES)") $(if $(SEND),--send)

mocks:            ## regenerate mocks/*.json (seeded, validated against the schemas)
	$(PY) scripts/make_mocks.py

openapi:          ## write docs/openapi.json from the FastAPI app
	$(PY) -m vaspfusion.cli openapi --out docs/openapi.json

types: openapi    ## generate ui/src/api/types.ts from the OpenAPI schema
	cd ui && npx --yes openapi-typescript@7.13.0 ../docs/openapi.json -o src/api/types.ts

ui-setup:         ## install the interface's dependencies (needs network ONCE)
	cd ui && npm ci

ui-dev:           ## the interface on :5173 with demo fixtures; API=live talks to `make serve` instead
	cd ui && VITE_API=$(or $(API),mock) npm run dev

ui-test:          ## the interface's tests, type check and lint
	cd ui && npm test && npm run typecheck && npm run lint

ui-build:         ## compile ui/ into ui/dist, which `make serve` then serves at /
	cd ui && npm run build

ui-shots:         ## screenshots of /kit and the shell into docs/screenshots/ (needs `make ui-dev` running; BASE_URL=..)
	cd ui && npm run screenshots

offline-check:    ## fail if code outside vaspfusion/chains/ can reach the network
	@! grep -rnE "https?://" --include=*.py --exclude-dir=chains vaspfusion/ \
		| grep -vE "#|\"\"\"|docs|example\.com|source_url|SOURCE_URL|xmlns=" \
		|| (echo "FAIL: a runtime URL is present outside vaspfusion/chains/" && exit 1)
	@! grep -rnE "^\s*(import|from) (urllib\.request|http\.client|socket|requests|httpx)" \
		--include=*.py --exclude=http.py vaspfusion/ \
		|| (echo "FAIL: only vaspfusion/chains/http.py may open sockets" && exit 1)
	@echo "PASS: the only outbound code is vaspfusion/chains/ (chain APIs), and OFFLINE=1 serves it from the cache."

reproduce:        ## regenerate every artifact that comes from tracked files and check nothing changed (no network)
	$(PY) scripts/reproduce.py

GIT_COMMIT := $(shell git rev-parse HEAD 2>/dev/null || echo unknown)
IMAGE   ?= vasp-fusion:offline
docker:           ## build the offline image (needs data/labels.duckdb: `make labels`); UI=build adds the interface
	@test -f data/labels.duckdb || (echo "data/labels.duckdb is missing: run 'make labels' first" && exit 1)
	GIT_COMMIT=$(GIT_COMMIT) docker compose build

docker-up:        ## run it on http://127.0.0.1:$(PORT) (sign in with the account in demo/officer.json)
	GIT_COMMIT=$(GIT_COMMIT) PORT=$(PORT) docker compose up -d
	@echo "http://127.0.0.1:$(PORT)  |  stop: make docker-down  |  back to the image's demo data: docker compose down -v"

docker-down:      ## stop it (its data volume is kept)
	docker compose down

docker-smoke:     ## drive the whole demo inside a throwaway container that has NO network
	docker run --rm --network none $(IMAGE) python scripts/docker_smoke.py --serve

# The audit log (data/audit.duckdb) and the officer accounts are never removed here.
clean:
	rm -rf data/labels.duckdb data/case.duckdb data/desk.duckdb data/sahyog_outbox data/demo_cache.duckdb ui/dist
