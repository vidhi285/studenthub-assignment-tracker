# syntax=docker/dockerfile:1
# StudentHub image. Stages:
#   base        Python + runtime dependencies
#   test        base + pytest + source  (used by `docker compose --profile test run --rm tests`)
#   production  final image (default target) run by Gunicorn as a non-root user

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM base AS test
COPY requirements-dev.txt .
RUN pip install -r requirements-dev.txt
COPY . .
USER app
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS production
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    APP_ENV=production
COPY app.py config.py wsgi.py manage.py gunicorn.conf.py ./
COPY studenthub/ studenthub/
COPY templates/ templates/
COPY static/ static/
COPY database/ database/
COPY scripts/healthcheck.py scripts/healthcheck.py
COPY docker/entrypoint.sh /usr/local/bin/studenthub-entrypoint
# Strip Windows line endings in case the repo was checked out with CRLF.
RUN sed -i 's/\r$//' /usr/local/bin/studenthub-entrypoint && chmod 0755 /usr/local/bin/studenthub-entrypoint
USER app
EXPOSE 5000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "scripts/healthcheck.py", "http://127.0.0.1:5000/health"]
ENTRYPOINT ["studenthub-entrypoint"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "wsgi:app"]
