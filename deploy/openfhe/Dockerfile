FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-openfhe.txt pyproject.toml /app/
COPY src /app/src
COPY scripts/run_openfhe_multiparty.py /app/scripts/run_openfhe_multiparty.py
RUN pip install -r requirements-openfhe.txt && pip install --no-deps .

RUN useradd --create-home --uid 10002 openfhe && \
    mkdir -p /output && chown -R openfhe:openfhe /output
USER openfhe

ENTRYPOINT ["python", "/app/scripts/run_openfhe_multiparty.py"]
CMD ["--output", "/output/summary.json"]
