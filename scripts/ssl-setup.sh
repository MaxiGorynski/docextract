#!/bin/bash
# ==============================================================================
# FILE: ssl-setup.sh
# LOCATION: /docextract/scripts/ssl-setup.sh
# ==============================================================================
#
# PURPOSE:
#   Automates SSL/TLS certificate setup using Let's Encrypt Certbot.
#   Handles initial certificate issuance and configures automatic renewal.
#
# PREREQUISITES:
#   - Domain DNS pointing to this server
#   - Port 80 accessible from internet (for ACME challenge)
#   - Docker and Docker Compose installed
#   - Nginx container running (serves ACME challenges)
#
# USAGE:
#   Initial certificate setup:
#       ./scripts/ssl-setup.sh --domain yourdomain.com --email admin@yourdomain.com
#
#   With www subdomain:
#       ./scripts/ssl-setup.sh --domain yourdomain.com --email admin@yourdomain.com --www
#
#   Dry run (test without obtaining certificate):
#       ./scripts/ssl-setup.sh --domain yourdomain.com --email admin@yourdomain.com --dry-run
#
#   Renew certificates:
#       ./scripts/ssl-setup.sh --renew
#
# OPTIONS:
#   --domain DOMAIN    Primary domain name (required for initial setup)
#   --email EMAIL      Email for Let's Encrypt notifications (required)
#   --www              Also obtain certificate for www.DOMAIN
#   --dry-run          Test the process without obtaining certificate
#   --renew            Renew existing certificates
#   --help             Show this help message
#
# AUTOMATIC RENEWAL:
#   After initial setup, add this to crontab for automatic renewal:
#       0 12 * * * /home/deploy/docextract/scripts/ssl-setup.sh --renew >> /home/deploy/logs/ssl-renewal.log 2>&1
#
# POST-SETUP STEPS:
#   1. Update nginx/conf.d/default.conf with your domain
#   2. Uncomment the HTTPS server block
#   3. Restart nginx: docker compose -f docker-compose.prod.yml restart nginx
#   4. Enable HTTPS in .env:
#      SECURE_SSL_REDIRECT=true
#      SESSION_COOKIE_SECURE=true
#      CSRF_COOKIE_SECURE=true
#
# CERTIFICATE LOCATION:
#   Certificates are stored in ./certbot/conf/live/DOMAIN/
#   - fullchain.pem: Full certificate chain
#   - privkey.pem: Private key
#
# ==============================================================================

set -e  # Exit on any error

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="docker-compose.prod.yml"
CERTBOT_DIR="$PROJECT_DIR/certbot"
DOMAIN=""
EMAIL=""
INCLUDE_WWW=false
DRY_RUN=false
RENEW_MODE=false

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

# =============================================================================
# Functions
# =============================================================================

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1"
    exit 1
}

show_help() {
    head -55 "$0" | grep -E "^#" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

check_prerequisites() {
    log "Checking prerequisites..."

    # Check Docker
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
    fi

    # Check Docker Compose
    if ! docker compose version &> /dev/null; then
        error "Docker Compose is not installed"
    fi

    # Check certbot directories exist
    mkdir -p "$CERTBOT_DIR/conf"
    mkdir -p "$CERTBOT_DIR/www"

    log "Prerequisites check passed"
}

check_nginx_running() {
    log "Checking if Nginx is running..."

    cd "$PROJECT_DIR"

    if ! docker compose -f "$COMPOSE_FILE" ps nginx 2>/dev/null | grep -q "running"; then
        warn "Nginx is not running. Starting it now..."
        docker compose -f "$COMPOSE_FILE" up -d nginx
        sleep 5
    fi

    log "Nginx is running"
}

check_domain_dns() {
    log "Checking DNS for $DOMAIN..."

    # Get server's public IP
    local server_ip=$(curl -s ifconfig.me 2>/dev/null || curl -s ipinfo.io/ip 2>/dev/null)

    if [ -z "$server_ip" ]; then
        warn "Could not determine server's public IP"
        return 0
    fi

    # Get domain's DNS record
    local domain_ip=$(dig +short "$DOMAIN" 2>/dev/null | head -1)

    if [ -z "$domain_ip" ]; then
        warn "Could not resolve DNS for $DOMAIN"
        warn "Make sure DNS is configured correctly before proceeding"
    elif [ "$server_ip" != "$domain_ip" ]; then
        warn "DNS mismatch: $DOMAIN points to $domain_ip, but this server is $server_ip"
        warn "Certificate issuance may fail if DNS is not correct"
    else
        log "DNS check passed: $DOMAIN -> $server_ip"
    fi
}

obtain_certificate() {
    log "Obtaining SSL certificate for $DOMAIN..."

    # Build domain arguments
    local domain_args="-d $DOMAIN"
    if [ "$INCLUDE_WWW" = true ]; then
        domain_args="$domain_args -d www.$DOMAIN"
    fi

    # Build certbot command
    local certbot_cmd="certonly --webroot -w /var/www/certbot"
    certbot_cmd="$certbot_cmd $domain_args"
    certbot_cmd="$certbot_cmd --email $EMAIL"
    certbot_cmd="$certbot_cmd --agree-tos"
    certbot_cmd="$certbot_cmd --no-eff-email"
    certbot_cmd="$certbot_cmd --non-interactive"

    if [ "$DRY_RUN" = true ]; then
        certbot_cmd="$certbot_cmd --dry-run"
        log "Running in dry-run mode (no certificate will be issued)"
    fi

    # Run certbot in a container
    docker run --rm \
        -v "$CERTBOT_DIR/conf:/etc/letsencrypt" \
        -v "$CERTBOT_DIR/www:/var/www/certbot" \
        certbot/certbot $certbot_cmd

    if [ "$DRY_RUN" = true ]; then
        log "Dry run completed successfully!"
        log "Run without --dry-run to obtain actual certificate"
    else
        log "Certificate obtained successfully!"
        log "Certificate location: $CERTBOT_DIR/conf/live/$DOMAIN/"
    fi
}

renew_certificates() {
    log "Renewing SSL certificates..."

    # Check if any certificates exist
    if [ ! -d "$CERTBOT_DIR/conf/live" ]; then
        error "No certificates found. Run initial setup first."
    fi

    # Run certbot renew
    docker run --rm \
        -v "$CERTBOT_DIR/conf:/etc/letsencrypt" \
        -v "$CERTBOT_DIR/www:/var/www/certbot" \
        certbot/certbot renew --non-interactive

    # Reload nginx to pick up renewed certificates
    log "Reloading Nginx..."
    cd "$PROJECT_DIR"
    docker compose -f "$COMPOSE_FILE" exec nginx nginx -s reload 2>/dev/null || true

    log "Certificate renewal completed!"
}

show_post_setup_instructions() {
    log ""
    log "=============================================="
    log "SSL Setup Complete - Next Steps"
    log "=============================================="
    log ""
    log "1. Update nginx/conf.d/default.conf:"
    log "   - Replace 'docextract.example.com' with '$DOMAIN'"
    log "   - Uncomment the HTTPS server block (remove HTTPS_START/HTTPS_END comments)"
    log ""
    log "2. Restart Nginx:"
    log "   docker compose -f docker-compose.prod.yml restart nginx"
    log ""
    log "3. Enable HTTPS in your .env file:"
    log "   SECURE_SSL_REDIRECT=true"
    log "   SESSION_COOKIE_SECURE=true"
    log "   CSRF_COOKIE_SECURE=true"
    log "   SECURE_HSTS_SECONDS=31536000"
    log ""
    log "4. Restart the web service:"
    log "   docker compose -f docker-compose.prod.yml restart web"
    log ""
    log "5. Set up automatic renewal (add to crontab):"
    log "   0 12 * * * $SCRIPT_DIR/ssl-setup.sh --renew >> /home/deploy/logs/ssl-renewal.log 2>&1"
    log ""
    log "=============================================="
}

update_nginx_config() {
    log "Updating Nginx configuration with domain..."

    local nginx_conf="$PROJECT_DIR/nginx/conf.d/default.conf"

    if [ -f "$nginx_conf" ]; then
        # Replace placeholder domain with actual domain
        sed -i "s/docextract\.example\.com/$DOMAIN/g" "$nginx_conf"
        log "Updated $nginx_conf with domain: $DOMAIN"
    else
        warn "Nginx config not found at $nginx_conf"
        warn "Please update manually"
    fi
}

# =============================================================================
# Parse Arguments
# =============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --domain)
            DOMAIN="$2"
            shift 2
            ;;
        --email)
            EMAIL="$2"
            shift 2
            ;;
        --www)
            INCLUDE_WWW=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --renew)
            RENEW_MODE=true
            shift
            ;;
        --help|-h)
            show_help
            ;;
        *)
            error "Unknown option: $1. Use --help for usage."
            ;;
    esac
done

# =============================================================================
# Validation
# =============================================================================

if [ "$RENEW_MODE" = false ]; then
    if [ -z "$DOMAIN" ]; then
        error "Domain is required. Use --domain yourdomain.com"
    fi

    if [ -z "$EMAIL" ]; then
        error "Email is required. Use --email admin@yourdomain.com"
    fi
fi

# =============================================================================
# Main Execution
# =============================================================================

log "=============================================="
log "DocExtract SSL Setup Script"
log "=============================================="

if [ "$RENEW_MODE" = true ]; then
    log "Mode: Certificate Renewal"
    check_prerequisites
    renew_certificates
else
    log "Domain: $DOMAIN"
    if [ "$INCLUDE_WWW" = true ]; then
        log "Also including: www.$DOMAIN"
    fi
    log "Email: $EMAIL"
    if [ "$DRY_RUN" = true ]; then
        log "Mode: Dry Run"
    else
        log "Mode: Initial Setup"
    fi
    log ""

    check_prerequisites
    check_nginx_running
    check_domain_dns
    obtain_certificate

    if [ "$DRY_RUN" = false ]; then
        update_nginx_config
        show_post_setup_instructions
    fi
fi

log ""
log "Done!"