# --- Build stage (compile C extensions, then discard gcc) ---
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.txt

# --- Runtime stage ---
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# upgrade picks up Debian security fixes newer than the base image.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# pip is not used at runtime, and its vendored copies of urllib3/msgpack lag
# behind the pinned versions and trip the image scan.
RUN python -m pip uninstall -y pip

WORKDIR /app

COPY . .

RUN chmod +x entrypoint.sh && \
    adduser --disabled-password --gecos '' appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
