# syntax=docker/dockerfile:1
# VASP-FUSION, the offline demo image: one container, one port, no network at run time.
#
#   make docker        build it (needs data/labels.duckdb: `make labels` first)
#   make docker-up     http://127.0.0.1:8000
#   make docker-smoke  drive the whole demo inside a container that has no network
#
# What is baked in, all from files in this repository plus the label database:
#   * the label database (data/labels.duckdb, built by `make labels`);
#   * the chain responses the eight demo wallets' traces read, replayed from the recorded
#     fixtures (tests/fixtures/demo) into a chain cache: `cli demo-cache`, no network;
#   * the eight demo cases, traced from that cache while the image is built. The build
#     FAILS unless each one reproduces its golden findings fingerprint and verifies.
# The build itself needs the network once (base images, Python wheels). The result can be
# carried to an air-gapped machine with `docker save` / `docker load`.

# ---- the interface: UI=build compiles ui/; UI=none (the default) leaves an empty dist,
# and the API serves its own console page instead. One stage with a condition, so it
# behaves the same under BuildKit and under the classic builder.
# Node 22: react-router 8 and Vitest ask for 22.12 or newer.
FROM node:22-slim AS ui
ARG UI=none
WORKDIR /ui
COPY ui/ ./
RUN if [ "$UI" = "build" ]; then npm ci && npm run build && node scripts/check-bundle.mjs; else mkdir -p dist; fi

# ---- code and dependencies
FROM python:3.12-slim AS base
# libgomp is LightGBM's OpenMP runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY vaspfusion/ ./vaspfusion/
COPY artifacts/ ./artifacts/
COPY demo/ ./demo/
COPY mocks/ ./mocks/
COPY docs/ ./docs/
COPY scripts/docker_smoke.py ./scripts/docker_smoke.py
COPY tests/golden/fingerprints.json ./tests/golden/fingerprints.json
COPY data/vasp_directory.yaml ./data/vasp_directory.yaml
ARG GIT_COMMIT=unknown
# OFFLINE=1: a chain request that is not in the cache is refused, never fetched.
# ETHERSCAN_API_KEY: any value selects the backend the cached pages were recorded from;
# it is never sent while OFFLINE=1. Pass a real key (and OFFLINE=0) for live traces.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app \
    OFFLINE=1 ETHERSCAN_API_KEY=offline-replay \
    VASPFUSION_GIT_COMMIT=${GIT_COMMIT}

# ---- the demo data, built and checked
FROM base AS data
COPY data/labels.duckdb ./data/labels.duckdb
COPY tests/fixtures/demo/ ./tests/fixtures/demo/
RUN python -m vaspfusion.cli demo-cache --out data/chain_cache.duckdb \
 && python -m vaspfusion.cli demo --golden tests/golden/fingerprints.json \
 && python -m vaspfusion.cli verify --all \
 && python -m vaspfusion.cli officer demo

# ---- the image
FROM base
COPY --from=data /app/data/ ./data/
COPY --from=ui /ui/dist ./ui/dist
RUN useradd --system --uid 10001 --home-dir /app vasp && chown -R vasp /app/data
USER vasp
EXPOSE 8000
VOLUME ["/app/data"]
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "-m", "vaspfusion.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
