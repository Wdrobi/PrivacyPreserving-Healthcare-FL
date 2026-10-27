FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements-services.txt pyproject.toml /app/
COPY src /app/src
COPY scripts/start_attested_authority.py /app/scripts/start_attested_authority.py
COPY scripts/start_stateful_witness.py /app/scripts/start_stateful_witness.py
RUN pip install --upgrade pip && \
    pip install -r requirements-services.txt && \
    pip install --no-deps .

RUN useradd --create-home --uid 10001 healthfl && \
    mkdir -p /state && chown -R healthfl:healthfl /state
USER healthfl
