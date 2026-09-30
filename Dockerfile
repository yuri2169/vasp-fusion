# One container, one port. B9 turns this into the fully offline image (vendored
# wheels, recorded demo data); for now it installs from the network.
FROM node:20-slim AS ui
WORKDIR /ui
COPY ui/package*.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim
# libgomp is LightGBM's OpenMP runtime.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY vaspfusion/ ./vaspfusion/
RUN pip install --no-cache-dir ".[dev]"
COPY mocks/ ./mocks/
COPY docs/ ./docs/
COPY tests/ ./tests/
COPY scripts/ ./scripts/
COPY --from=ui /ui/dist ./ui/dist
# The label DB is built from ../research/data, which is outside this repo:
# `make labels` on the host, then mount data/ (or bake it in, B9).
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
EXPOSE 8000
VOLUME ["/app/data"]
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["python", "-m", "vaspfusion.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
