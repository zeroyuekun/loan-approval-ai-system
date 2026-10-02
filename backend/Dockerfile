# --- Build stage (compile C extensions, then discard gcc) ---
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

# --- Runtime base (shared by the dev and runtime stages) ---
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# upgrade picks up Debian security fixes newer than the base image.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app

# --- Development stage (docker compose only, never shipped) ---
# Keeps pip and adds the test, type-check and audit tools that the Makefile
# runs inside the backend container (make test / typecheck / security).
FROM base AS dev

COPY requirements.txt requirements-dev.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements-dev.txt

COPY . .

RUN chmod +x entrypoint.sh && \
    adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]

# --- Runtime stage (the default target: keep it last) ---
FROM base

# pip is not used at runtime, and its vendored copies of urllib3/msgpack lag
# behind the pinned versions and trip the image scan.
RUN python -m pip uninstall -y pip

COPY . .

RUN chmod +x entrypoint.sh && \
    adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
