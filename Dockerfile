# ==============================================================================
# FILE: Dockerfile
# LOCATION: /docextract/Dockerfile (project root)
# ==============================================================================
#
# PURPOSE:
#   Container image definition for DocExtract Django application.
#   Used by both development (docker-compose.yml) and production
#   (docker-compose.prod.yml) deployments.
#
# BUILD STAGES:
#   Single stage build optimised for both development iteration speed
#   and production image size. Build dependencies are removed after
#   pip install to reduce final image size.
#
# BASE IMAGE:
#   Python 3.11 slim - balance of size (~150MB) and compatibility.
#   Alpine was considered but has musl libc issues with some packages.
#
# SYSTEM DEPENDENCIES:
#   - libmagic1: Required by python-magic for file type detection
#   - libpq5: Required by psycopg2 for PostgreSQL connections
#   - curl: Required for health checks
#
# USAGE:
#   Build image:
#       docker build -t docextract .
#
#   Run container:
#       docker run -p 8000:8000 docextract
#
#   Via docker-compose (recommended):
#       docker-compose up --build
#
# ENVIRONMENT VARIABLES (required at runtime):
#   - DJANGO_SETTINGS_MODULE: config.settings.development or .production
#   - POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_HOST
#   - REDIS_URL
#   - SECRET_KEY (production only)
#
# VOLUMES:
#   Mount these for persistence:
#   - /app/media: User-uploaded documents
#   - /app/staticfiles: Collected static files (production)
#
# SECURITY:
#   - Runs as non-root user (appuser) with UID 1000
#   - No shell history or cache files
#   - Build dependencies removed after use
#
# PERFORMANCE:
#   - Static files collected during build (not at runtime)
#   - pip cache disabled to reduce layer size
#   - Multi-stage not used to allow dev volume mounts
#
# ==============================================================================

FROM python:3.11-slim

# ---------------------------------------------------------------------------
# Environment Configuration
# ---------------------------------------------------------------------------
# Prevent Python from writing bytecode (.pyc files)
ENV PYTHONDONTWRITEBYTECODE=1
# Ensure Python output is sent straight to terminal (for logging)
ENV PYTHONUNBUFFERED=1
# Disable pip cache to reduce image size
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# ---------------------------------------------------------------------------
# Set Work Directory
# ---------------------------------------------------------------------------
WORKDIR /app

# ---------------------------------------------------------------------------
# Install System Dependencies
# ---------------------------------------------------------------------------
# Split into build-time and runtime dependencies
# Build deps (gcc, libpq-dev) are removed after pip install
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Runtime dependencies
    libmagic1 \
    libpq5 \
    curl \
    # Build dependencies (removed later)
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Install Python Dependencies
# ---------------------------------------------------------------------------
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Remove Build Dependencies
# ---------------------------------------------------------------------------
# Reduces image size by ~100MB
RUN apt-get purge -y --auto-remove gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /root/.cache

# ---------------------------------------------------------------------------
# Create Non-Root User
# ---------------------------------------------------------------------------
# Security: Run application as non-root user
RUN useradd --create-home --shell /bin/bash --uid 1000 appuser

# ---------------------------------------------------------------------------
# Create Required Directories
# ---------------------------------------------------------------------------
# These will be mounted as volumes in production
RUN mkdir -p /app/media /app/staticfiles /app/logs \
    && chown -R appuser:appuser /app

# ---------------------------------------------------------------------------
# Copy Application Code
# ---------------------------------------------------------------------------
COPY --chown=appuser:appuser . .

# ---------------------------------------------------------------------------
# Collect Static Files
# ---------------------------------------------------------------------------
# Run collectstatic during build for production
# Uses a dummy SECRET_KEY since we're not running the app yet
# DJANGO_SETTINGS_MODULE defaults to development but collectstatic works either way
RUN SECRET_KEY=build-time-secret \
    DJANGO_SETTINGS_MODULE=config.settings.development \
    python manage.py collectstatic --noinput --clear

# ---------------------------------------------------------------------------
# Switch to Non-Root User
# ---------------------------------------------------------------------------
USER appuser

# ---------------------------------------------------------------------------
# Expose Port
# ---------------------------------------------------------------------------
EXPOSE 8000

# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------
# Used by Docker and orchestrators to verify container health
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# ---------------------------------------------------------------------------
# Default Command
# ---------------------------------------------------------------------------
# Overridden in docker-compose.yml for development (runserver)
# Production uses this Gunicorn command
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--worker-class", "gthread", "--timeout", "120"]