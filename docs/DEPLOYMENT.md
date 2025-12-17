# ==============================================================================
# FILE: DEPLOYMENT.md
# LOCATION: /docextract/docs/DEPLOYMENT.md
# ==============================================================================
#
# PURPOSE:
#   Production deployment guide for DocExtract on Hetzner VPS.
#   Covers server setup, Docker configuration, SSL, and operations.
#
# ==============================================================================

# Deployment Guide

This guide covers deploying DocExtract to a Hetzner VPS using Docker Compose.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Infrastructure Overview](#infrastructure-overview)
3. [Server Setup](#server-setup)
4. [Deployment](#deployment)
5. [SSL Configuration](#ssl-configuration)
6. [Operations](#operations)
7. [Monitoring](#monitoring)
8. [Backup & Recovery](#backup--recovery)
9. [Troubleshooting](#troubleshooting)

---

## Quick Start

For experienced users, here's the condensed deployment process:

```bash
# 1. SSH to server and clone repository
ssh deploy@your-server
git clone <repository-url> ~/docextract
cd ~/docextract

# 2. Configure environment
cp .env.production.example .env
nano .env  # Fill in SECRET_KEY, POSTGRES_PASSWORD, OPENAI_API_KEY, domain

# 3. Deploy
./scripts/deploy.sh --init

# 4. Create admin user
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser

# 5. Set up SSL
./scripts/ssl-setup.sh --domain yourdomain.com --email admin@yourdomain.com

# 6. Enable HTTPS in .env
# Add: SECURE_SSL_REDIRECT=true, SESSION_COOKIE_SECURE=true, CSRF_COOKIE_SECURE=true

# 7. Restart
docker compose -f docker-compose.prod.yml restart web
```

---

## Infrastructure Overview

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Hetzner VPS (CX21)                       │
│                                                             │
│   Internet ──▶ Nginx (:80/:443) ──▶ Django (Gunicorn)       │
│                  │                        │                 │
│                  │                        ▼                 │
│            static/media              PostgreSQL             │
│                                          │                  │
│                                          ▼                  │
│                                    Redis ◀── Celery         │
│                                                             │
│   Volumes: postgres_data, redis_data, static, media         │
└─────────────────────────────────────────────────────────────┘
```

### Production Files

| File | Purpose |
|------|---------|
| `docker-compose.prod.yml` | Production service orchestration |
| `nginx/nginx.conf` | Nginx main configuration |
| `nginx/conf.d/default.conf` | Server blocks, SSL, proxy settings |
| `.env.production.example` | Environment variable template |
| `scripts/deploy.sh` | Deployment automation |
| `scripts/backup.sh` | Database and media backup |
| `scripts/restore.sh` | Restore from backup |
| `scripts/ssl-setup.sh` | SSL certificate automation |
| `scripts/health-check.sh` | Service health monitoring |

### Resource Requirements

| Tier | Server | Specs | Monthly Cost |
|------|--------|-------|--------------|
| Minimum | CX21 | 2 vCPU, 4GB RAM, 40GB SSD | €5.83 |
| Recommended | CX31 | 2 vCPU, 8GB RAM, 80GB SSD | €10.49 |
| Production | CX41 | 4 vCPU, 16GB RAM, 160GB SSD | €18.49 |

---

## Server Setup

### 1. Create Hetzner Server

Via Hetzner Cloud Console:
- Image: Ubuntu 24.04
- Type: CX21 or higher
- Location: Nuremberg (nbg1) or Falkenstein (fsn1)
- Add your SSH key

### 2. Initial Server Configuration

```bash
# Connect as root
ssh root@<server-ip>

# Update system
apt update && apt upgrade -y

# Install essentials
apt install -y curl git ufw fail2ban

# Configure firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow http
ufw allow https
ufw enable
```

### 3. Create Deploy User

```bash
# Create user
adduser deploy
usermod -aG sudo deploy

# Setup SSH
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh

# Disable root SSH (optional but recommended)
sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart sshd
```

### 4. Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Add deploy user to docker group
usermod -aG docker deploy

# Verify
docker --version
docker compose version
```

---

## Deployment

### Initial Deployment

```bash
# Switch to deploy user
su - deploy

# Clone repository
git clone <repository-url> ~/docextract
cd ~/docextract

# Create environment file
cp .env.production.example .env
```

Edit `.env` with your values:

```bash
# Generate secret key
python3 -c "import secrets; print(secrets.token_urlsafe(50))"

# Generate database password
openssl rand -base64 32
```

Required `.env` values:
```
SECRET_KEY=<generated-secret-key>
ALLOWED_HOSTS=yourdomain.com
POSTGRES_PASSWORD=<generated-password>
OPENAI_API_KEY=sk-your-key
CSRF_TRUSTED_ORIGINS=https://yourdomain.com
```

Run initial deployment:
```bash
./scripts/deploy.sh --init
```

Create superuser:
```bash
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

### Update Deployment

For subsequent updates:

```bash
./scripts/deploy.sh
```

This will:
1. Pull latest code
2. Build new images
3. Run migrations
4. Collect static files
5. Restart services
6. Verify health

### Rollback

If something goes wrong:

```bash
./scripts/deploy.sh --rollback
```

---

## SSL Configuration

### Obtain Certificate

```bash
./scripts/ssl-setup.sh --domain yourdomain.com --email admin@yourdomain.com
```

For www subdomain:
```bash
./scripts/ssl-setup.sh --domain yourdomain.com --email admin@yourdomain.com --www
```

### Enable HTTPS

After obtaining the certificate:

1. **Update Nginx config** (already done by ssl-setup.sh):
   ```bash
   # Verify domain is set correctly
   grep server_name nginx/conf.d/default.conf
   ```

2. **Restart Nginx**:
   ```bash
   docker compose -f docker-compose.prod.yml restart nginx
   ```

3. **Enable HTTPS in Django** - add to `.env`:
   ```
   SECURE_SSL_REDIRECT=true
   SESSION_COOKIE_SECURE=true
   CSRF_COOKIE_SECURE=true
   SECURE_HSTS_SECONDS=31536000
   ```

4. **Restart web service**:
   ```bash
   docker compose -f docker-compose.prod.yml restart web
   ```

### Certificate Renewal

Certificates auto-renew. Add to crontab:

```bash
crontab -e
```

Add:
```
0 12 * * * /home/deploy/docextract/scripts/ssl-setup.sh --renew >> /home/deploy/logs/ssl-renewal.log 2>&1
```

---

## Operations

### Common Commands

```bash
# View logs
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f celery_worker

# Restart specific service
docker compose -f docker-compose.prod.yml restart web

# Run Django management command
docker compose -f docker-compose.prod.yml exec web python manage.py <command>

# Django shell
docker compose -f docker-compose.prod.yml exec web python manage.py shell

# Database shell
docker compose -f docker-compose.prod.yml exec db psql -U docextract docextract

# View running containers
docker compose -f docker-compose.prod.yml ps
```

### Scaling Celery Workers

```bash
docker compose -f docker-compose.prod.yml up -d --scale celery_worker=3
```

### Viewing Resource Usage

```bash
docker stats
```

---

## Monitoring

### Health Check

```bash
# Human-readable output
./scripts/health-check.sh

# JSON output (for monitoring systems)
./scripts/health-check.sh --json

# Quiet mode (exit code only)
./scripts/health-check.sh --quiet
```

### Automated Monitoring

Add to crontab for alerts:

```bash
*/5 * * * * /home/deploy/docextract/scripts/health-check.sh --quiet || echo "DocExtract unhealthy" | mail -s "Health Alert" admin@example.com
```

### Health Endpoint

The application exposes `/health/` which returns:

```json
{
  "status": "healthy",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

---

## Backup & Recovery

### Manual Backup

```bash
./scripts/backup.sh
```

### Automated Backups

Add to crontab for daily 3 AM backups:

```bash
0 3 * * * /home/deploy/docextract/scripts/backup.sh >> /home/deploy/logs/backup.log 2>&1
```

### Backup Options

```bash
# Database only
./scripts/backup.sh --db-only

# Media only
./scripts/backup.sh --media-only

# Custom retention (days)
./scripts/backup.sh --retention 14
```

### List Available Backups

```bash
./scripts/restore.sh --list
```

### Restore from Backup

```bash
# Restore database
./scripts/restore.sh --db backups/db_20251217_030000.sql.gz

# Restore media
./scripts/restore.sh --media backups/media_20251217_030000.tar.gz

# Restore both
./scripts/restore.sh --db backups/db_backup.sql.gz --media backups/media_backup.tar.gz
```

### Offsite Backup

Consider syncing backups to remote storage:

```bash
# Example: rsync to another server
rsync -avz ~/docextract/backups/ backup-server:/backups/docextract/

# Example: AWS S3
aws s3 sync ~/docextract/backups/ s3://your-bucket/docextract-backups/
```

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker compose -f docker-compose.prod.yml logs web

# Check container status
docker compose -f docker-compose.prod.yml ps

# Rebuild and restart
docker compose -f docker-compose.prod.yml up -d --build web
```

### Database Connection Errors

```bash
# Verify database is running
docker compose -f docker-compose.prod.yml ps db

# Test connection
docker compose -f docker-compose.prod.yml exec db psql -U docextract -c "SELECT 1"

# Check credentials in .env
grep POSTGRES .env
```

### Celery Tasks Not Processing

```bash
# Check worker logs
docker compose -f docker-compose.prod.yml logs celery_worker

# Verify Redis
docker compose -f docker-compose.prod.yml exec redis redis-cli ping

# Check queue
docker compose -f docker-compose.prod.yml exec redis redis-cli llen celery
```

### 502 Bad Gateway

Usually means Django/Gunicorn isn't responding:

```bash
# Check web container
docker compose -f docker-compose.prod.yml logs web

# Restart web
docker compose -f docker-compose.prod.yml restart web
```

### High Memory Usage

```bash
# Check memory
docker stats --no-stream

# Restart to clear
docker compose -f docker-compose.prod.yml restart

# Reduce Gunicorn workers (edit docker-compose.prod.yml)
# Change --workers 3 to --workers 2
```

### SSL Certificate Issues

```bash
# Test renewal
./scripts/ssl-setup.sh --renew

# Check certificate expiry
openssl x509 -in certbot/conf/live/yourdomain.com/fullchain.pem -noout -dates

# Force renewal
docker run --rm -v $(pwd)/certbot/conf:/etc/letsencrypt certbot/certbot renew --force-renewal
```

### Disk Space

```bash
# Check usage
df -h

# Clean Docker
docker system prune -a --volumes

# Clean old backups
find ~/docextract/backups -mtime +30 -delete
```

---

## Environment Variables Reference

### Required

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `POSTGRES_PASSWORD` | Database password |

### Recommended

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | (none) |
| `CSRF_TRUSTED_ORIGINS` | HTTPS origins | (none) |

### HTTPS (enable after SSL setup)

| Variable | Description | Default |
|----------|-------------|---------|
| `SECURE_SSL_REDIRECT` | Redirect HTTP to HTTPS | `false` |
| `SESSION_COOKIE_SECURE` | Secure session cookies | `false` |
| `CSRF_COOKIE_SECURE` | Secure CSRF cookies | `false` |
| `SECURE_HSTS_SECONDS` | HSTS max-age | `0` |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES_DB` | Database name | `docextract` |
| `POSTGRES_USER` | Database user | `docextract` |
| `POSTGRES_HOST` | Database host | `db` |
| `REDIS_URL` | Redis connection | `redis://redis:6379/0` |
| `AI_EXTRACTION_ENABLED` | Enable AI extraction | `true` |

---

## Security Checklist

- [ ] SSH key authentication only (password auth disabled)
- [ ] Firewall configured (UFW)
- [ ] fail2ban installed
- [ ] Non-root deploy user
- [ ] Strong database password
- [ ] Unique Django SECRET_KEY
- [ ] SSL certificate installed
- [ ] HTTPS redirect enabled
- [ ] HSTS enabled
- [ ] Regular backups configured
- [ ] Backups tested (restore works)
- [ ] Monitoring alerts configured