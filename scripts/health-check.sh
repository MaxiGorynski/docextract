#!/bin/bash
# ==============================================================================
# FILE: health-check.sh
# LOCATION: /docextract/scripts/health-check.sh
# ==============================================================================
#
# PURPOSE:
#   Comprehensive health check script for DocExtract production environment.
#   Checks all services (web, database, Redis, Celery, Nginx) and reports
#   status with optional alerting.
#
# USAGE:
#   Basic check (human-readable output):
#       ./scripts/health-check.sh
#
#   JSON output (for monitoring systems):
#       ./scripts/health-check.sh --json
#
#   Quiet mode (exit code only):
#       ./scripts/health-check.sh --quiet
#
#   Specific service:
#       ./scripts/health-check.sh --service web
#
# EXIT CODES:
#   0 - All services healthy
#   1 - One or more services unhealthy
#   2 - Script error (missing dependencies, etc.)
#
# MONITORING INTEGRATION:
#   Add to crontab for periodic checks:
#       */5 * * * * /home/deploy/docextract/scripts/health-check.sh --quiet || echo "ALERT: DocExtract unhealthy" | mail -s "Health Check Failed" admin@example.com
#
#   Or use with monitoring tools (Prometheus, Datadog, etc.):
#       ./scripts/health-check.sh --json
#
# ==============================================================================

set -e

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="docker-compose.prod.yml"
OUTPUT_FORMAT="human"
CHECK_SERVICE=""
HEALTH_ENDPOINT="http://localhost:8000/health/"

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Results storage
declare -A RESULTS
OVERALL_STATUS="healthy"

# =============================================================================
# Functions
# =============================================================================

show_help() {
    head -40 "$0" | grep -E "^#" | sed 's/^# //' | sed 's/^#//'
    exit 0
}

check_docker() {
    if ! docker compose version &> /dev/null; then
        echo "Docker Compose not available"
        exit 2
    fi

    cd "$PROJECT_DIR"

    # Fall back to dev compose if prod doesn't exist
    if [ ! -f "$COMPOSE_FILE" ]; then
        COMPOSE_FILE="docker-compose.yml"
    fi
}

check_container_status() {
    local service="$1"
    local status

    status=$(docker compose -f "$COMPOSE_FILE" ps "$service" --format json 2>/dev/null | grep -o '"State":"[^"]*"' | cut -d'"' -f4)

    if [ "$status" = "running" ]; then
        echo "healthy"
    elif [ -z "$status" ]; then
        echo "not_found"
    else
        echo "unhealthy"
    fi
}

check_web() {
    local status="healthy"
    local message=""

    # Check container is running
    local container_status=$(check_container_status "web")
    if [ "$container_status" != "healthy" ]; then
        RESULTS["web"]="unhealthy:container_$container_status"
        OVERALL_STATUS="unhealthy"
        return
    fi

    # Check health endpoint
    local response
    response=$(docker compose -f "$COMPOSE_FILE" exec -T web python -c "
import urllib.request
import json
try:
    req = urllib.request.urlopen('http://localhost:8000/health/', timeout=10)
    data = json.loads(req.read().decode())
    print(json.dumps(data))
except Exception as e:
    print(json.dumps({'status': 'error', 'message': str(e)}))
" 2>/dev/null)

    if echo "$response" | grep -q '"status": "healthy"'; then
        RESULTS["web"]="healthy"
    else
        RESULTS["web"]="unhealthy:health_check_failed"
        OVERALL_STATUS="unhealthy"
    fi
}

check_database() {
    local container_status=$(check_container_status "db")
    if [ "$container_status" != "healthy" ]; then
        RESULTS["database"]="unhealthy:container_$container_status"
        OVERALL_STATUS="unhealthy"
        return
    fi

    # Test database connection
    local db_check
    db_check=$(docker compose -f "$COMPOSE_FILE" exec -T db pg_isready -U docextract 2>/dev/null)

    if echo "$db_check" | grep -q "accepting connections"; then
        RESULTS["database"]="healthy"
    else
        RESULTS["database"]="unhealthy:connection_refused"
        OVERALL_STATUS="unhealthy"
    fi
}

check_redis() {
    local container_status=$(check_container_status "redis")
    if [ "$container_status" != "healthy" ]; then
        RESULTS["redis"]="unhealthy:container_$container_status"
        OVERALL_STATUS="unhealthy"
        return
    fi

    # Test Redis connection
    local redis_check
    redis_check=$(docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli ping 2>/dev/null)

    if [ "$redis_check" = "PONG" ]; then
        RESULTS["redis"]="healthy"
    else
        RESULTS["redis"]="unhealthy:ping_failed"
        OVERALL_STATUS="unhealthy"
    fi
}

check_celery() {
    local container_status=$(check_container_status "celery_worker")

    # Fall back to 'celery' service name for dev compose
    if [ "$container_status" = "not_found" ]; then
        container_status=$(check_container_status "celery")
    fi

    if [ "$container_status" = "not_found" ]; then
        RESULTS["celery"]="not_configured"
        return
    fi

    if [ "$container_status" != "healthy" ]; then
        RESULTS["celery"]="unhealthy:container_$container_status"
        OVERALL_STATUS="unhealthy"
        return
    fi

    RESULTS["celery"]="healthy"
}

check_nginx() {
    local container_status=$(check_container_status "nginx")

    if [ "$container_status" = "not_found" ]; then
        RESULTS["nginx"]="not_configured"
        return
    fi

    if [ "$container_status" != "healthy" ]; then
        RESULTS["nginx"]="unhealthy:container_$container_status"
        OVERALL_STATUS="unhealthy"
        return
    fi

    # Test nginx config
    local nginx_check
    nginx_check=$(docker compose -f "$COMPOSE_FILE" exec -T nginx nginx -t 2>&1)

    if echo "$nginx_check" | grep -q "successful"; then
        RESULTS["nginx"]="healthy"
    else
        RESULTS["nginx"]="unhealthy:config_invalid"
        OVERALL_STATUS="unhealthy"
    fi
}

check_disk_space() {
    local usage
    usage=$(df -h "$PROJECT_DIR" | awk 'NR==2 {print $5}' | sed 's/%//')

    if [ "$usage" -lt 80 ]; then
        RESULTS["disk"]="healthy:${usage}%_used"
    elif [ "$usage" -lt 90 ]; then
        RESULTS["disk"]="warning:${usage}%_used"
    else
        RESULTS["disk"]="critical:${usage}%_used"
        OVERALL_STATUS="unhealthy"
    fi
}

output_human() {
    echo ""
    echo "=============================================="
    echo "DocExtract Health Check"
    echo "=============================================="
    echo "Time: $(date '+%Y-%m-%d %H:%M:%S')"
    echo ""

    for service in web database redis celery nginx disk; do
        local status="${RESULTS[$service]}"
        local icon

        if [[ "$status" == healthy* ]]; then
            icon="${GREEN}✓${NC}"
        elif [[ "$status" == warning* ]]; then
            icon="${YELLOW}⚠${NC}"
        elif [[ "$status" == not_configured* ]]; then
            icon="${YELLOW}○${NC}"
        else
            icon="${RED}✗${NC}"
        fi

        printf "  %b %-12s %s\n" "$icon" "$service:" "$status"
    done

    echo ""
    echo "----------------------------------------------"
    if [ "$OVERALL_STATUS" = "healthy" ]; then
        echo -e "Overall Status: ${GREEN}HEALTHY${NC}"
    else
        echo -e "Overall Status: ${RED}UNHEALTHY${NC}"
    fi
    echo "=============================================="
    echo ""
}

output_json() {
    local services_json=""
    local first=true

    for service in web database redis celery nginx disk; do
        local status="${RESULTS[$service]}"
        local healthy="true"

        if [[ "$status" != healthy* ]] && [[ "$status" != not_configured* ]] && [[ "$status" != warning* ]]; then
            healthy="false"
        fi

        if [ "$first" = true ]; then
            first=false
        else
            services_json="$services_json,"
        fi

        services_json="$services_json\"$service\":{\"status\":\"$status\",\"healthy\":$healthy}"
    done

    local overall_healthy="true"
    if [ "$OVERALL_STATUS" != "healthy" ]; then
        overall_healthy="false"
    fi

    echo "{\"timestamp\":\"$(date -Iseconds)\",\"overall_status\":\"$OVERALL_STATUS\",\"healthy\":$overall_healthy,\"services\":{$services_json}}"
}

run_all_checks() {
    check_web
    check_database
    check_redis
    check_celery
    check_nginx
    check_disk_space
}

run_single_check() {
    case "$CHECK_SERVICE" in
        web)
            check_web
            ;;
        db|database)
            check_database
            ;;
        redis)
            check_redis
            ;;
        celery)
            check_celery
            ;;
        nginx)
            check_nginx
            ;;
        disk)
            check_disk_space
            ;;
        *)
            echo "Unknown service: $CHECK_SERVICE"
            echo "Valid services: web, database, redis, celery, nginx, disk"
            exit 2
            ;;
    esac
}

# =============================================================================
# Parse Arguments
# =============================================================================

while [[ $# -gt 0 ]]; do
    case $1 in
        --json)
            OUTPUT_FORMAT="json"
            shift
            ;;
        --quiet|-q)
            OUTPUT_FORMAT="quiet"
            shift
            ;;
        --service|-s)
            CHECK_SERVICE="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            ;;
        *)
            echo "Unknown option: $1"
            exit 2
            ;;
    esac
done

# =============================================================================
# Main Execution
# =============================================================================

check_docker
cd "$PROJECT_DIR"

if [ -n "$CHECK_SERVICE" ]; then
    run_single_check
else
    run_all_checks
fi

# Output results
case "$OUTPUT_FORMAT" in
    json)
        output_json
        ;;
    quiet)
        # No output, just exit code
        ;;
    *)
        output_human
        ;;
esac

# Exit with appropriate code
if [ "$OVERALL_STATUS" = "healthy" ]; then
    exit 0
else
    exit 1
fi