#!/bin/bash
# Pve-Bot Maintenance & Operations Script
# Usage: ./maintenance.sh [command] [options]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

DATA_DIR="${DATA_DIR:-.}/data"
BACKUP_DIR="${BACKUP_DIR:-.}/backups"
LOG_FILE="${LOG_FILE:-.}/bot.log"

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# ============================================================================
# BACKUP OPERATIONS
# ============================================================================

backup_data() {
    log_info "Starting data backup..."

    mkdir -p "$BACKUP_DIR"

    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="$BACKUP_DIR/vouches_${timestamp}.json"

    if [ -f "$DATA_DIR/vouches.json" ]; then
        cp "$DATA_DIR/vouches.json" "$backup_file"
        gzip "$backup_file"
        log_success "Backup created: ${backup_file}.gz"

        # Keep only last 30 days of backups
        find "$BACKUP_DIR" -name "vouches_*.json.gz" -mtime +30 -delete
        log_info "Old backups cleaned (>30 days)"
    else
        log_error "No vouches.json found at $DATA_DIR/vouches.json"
        return 1
    fi
}

list_backups() {
    log_info "Available backups:"
    ls -lh "$BACKUP_DIR"/vouches_*.json.gz 2>/dev/null | while read line; do
        echo "  $line"
    done
}

restore_backup() {
    local backup_file=$1

    if [ -z "$backup_file" ]; then
        log_error "Usage: restore_backup <backup_file>"
        list_backups
        return 1
    fi

    if [ ! -f "$backup_file" ]; then
        log_error "Backup file not found: $backup_file"
        return 1
    fi

    log_warning "Restoring from backup: $backup_file"

    # Create safety backup of current file
    if [ -f "$DATA_DIR/vouches.json" ]; then
        cp "$DATA_DIR/vouches.json" "$DATA_DIR/vouches_pre_restore.json"
    fi

    # Restore
    if [[ "$backup_file" == *.gz ]]; then
        gunzip -c "$backup_file" > "$DATA_DIR/vouches.json"
    else
        cp "$backup_file" "$DATA_DIR/vouches.json"
    fi

    log_success "Restored from backup. Previous file saved as vouches_pre_restore.json"
}

# ============================================================================
# DATA VALIDATION & CLEANUP
# ============================================================================

validate_data() {
    log_info "Validating data file..."

    if [ ! -f "$DATA_DIR/vouches.json" ]; then
        log_error "Data file not found: $DATA_DIR/vouches.json"
        return 1
    fi

    # Check JSON validity
    if python3 -c "import json; json.load(open('$DATA_DIR/vouches.json'))" 2>/dev/null; then
        log_success "JSON structure valid"
    else
        log_error "JSON is corrupted"
        return 1
    fi

    # Check required fields
    python3 << 'EOF'
import json
import sys

try:
    with open('data/vouches.json', 'r') as f:
        data = json.load(f)

    issues = []
    for uid, record in data.items():
        if uid.isdigit():  # Only check user records
            if 'pve' not in record:
                issues.append(f"User {uid}: missing 'pve' category")
            if 'host_runs' not in record:
                issues.append(f"User {uid}: missing 'host_runs'")

    if issues:
        for issue in issues[:10]:  # Show first 10
            print(f"  ⚠ {issue}")
        if len(issues) > 10:
            print(f"  ... and {len(issues)-10} more issues")
    else:
        print("  ✓ All records have required fields")

except Exception as e:
    print(f"  ✗ Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF
}

cleanup_old_logs() {
    log_info "Cleaning up old bot logs..."

    # Archive logs older than 7 days
    if [ -f "$LOG_FILE" ]; then
        local size=$(du -h "$LOG_FILE" | cut -f1)

        if [ "$size" -gt "100M" ]; then
            local archive_name="$LOG_FILE.$(date +%Y%m%d_%H%M%S).old"
            mv "$LOG_FILE" "$archive_name"
            gzip "$archive_name"
            log_success "Log archived: $archive_name.gz"
            touch "$LOG_FILE"
        else
            log_info "Log size acceptable ($size)"
        fi
    fi
}

# ============================================================================
# DATABASE OPTIMIZATION
# ============================================================================

optimize_storage() {
    log_info "Optimizing data storage..."

    python3 << 'EOF'
import json
import sys
from datetime import datetime, timezone, timedelta

try:
    with open('data/vouches.json', 'r') as f:
        data = json.load(f)

    # Trim host_runs to last 100 (already done by bot, but ensure consistency)
    archival_count = 0

    for uid, record in data.items():
        if uid.isdigit():
            # Trim host runs to 100
            if 'host_runs' in record:
                original_len = len(record['host_runs'])
                record['host_runs'] = record['host_runs'][-100:]
                if original_len > 100:
                    archival_count += original_len - 100

    # Save optimized data
    with open('data/vouches.json', 'w') as f:
        json.dump(data, f, indent=2)

    print(f"  ✓ Trimmed {archival_count} old host run entries")
    print(f"  ✓ Database optimized")

except Exception as e:
    print(f"  ✗ Error: {e}", file=sys.stderr)
    sys.exit(1)
EOF
}

# ============================================================================
# MONITORING & DIAGNOSTICS
# ============================================================================

check_health() {
    log_info "Running health checks..."

    local issues=0

    # Check data file exists
    if [ ! -f "$DATA_DIR/vouches.json" ]; then
        log_error "Data file missing: $DATA_DIR/vouches.json"
        issues=$((issues + 1))
    else
        local size=$(du -h "$DATA_DIR/vouches.json" | cut -f1)
        log_success "Data file exists ($size)"
    fi

    # Check bot process (if running)
    if pgrep -f "python.*vouch_bot" > /dev/null; then
        log_success "Bot process running"
    else
        log_warning "Bot process not running (this is normal if stopped)"
    fi

    # Check disk space
    local available=$(df "$DATA_DIR" | tail -1 | awk '{print $4}')
    if [ "$available" -lt 1000000 ]; then  # Less than 1GB
        log_warning "Low disk space: ${available}KB available"
        issues=$((issues + 1))
    else
        log_success "Disk space adequate"
    fi

    # Check Python version
    local py_version=$(python3 --version 2>&1 | awk '{print $2}')
    log_success "Python version: $py_version"

    if [ $issues -eq 0 ]; then
        log_success "All health checks passed"
    else
        log_warning "$issues issue(s) detected"
    fi
}

show_stats() {
    log_info "Database statistics:"

    python3 << 'EOF'
import json
from datetime import datetime, timezone, timedelta

with open('data/vouches.json', 'r') as f:
    data = json.load(f)

# Count users
users = sum(1 for uid in data if uid.isdigit())
print(f"  Total members: {users}")

# Sum points
total_points = 0
total_vouches = 0
active_hosts = 0
dormant = 0

now = datetime.now(timezone.utc)

for uid, record in data.items():
    if uid.isdigit():
        # Points
        for cat in ['pve', 'security', 'support']:
            if cat in record:
                total_points += record[cat].get('total_points', 0)
                total_vouches += record[cat].get('total_vouches', 0)

        # Hosts
        if 'host_runs' in record and record['host_runs']:
            last_run = datetime.fromisoformat(record['host_runs'][-1])
            days_since = (now - last_run).days
            if days_since <= 30:
                active_hosts += 1
            elif days_since > 60:
                dormant += 1

print(f"  Total vouches: {total_vouches}")
print(f"  Total points: {total_points}")
print(f"  Active hosts (30d): {active_hosts}")
print(f"  Dormant members (60d): {dormant}")

# File size
import os
size_mb = os.path.getsize('data/vouches.json') / (1024*1024)
print(f"  Data file size: {size_mb:.2f}MB")
EOF
}

# ============================================================================
# SECURITY AUDIT
# ============================================================================

audit_threats() {
    log_info "Running security audit..."

    python3 << 'EOF'
import json
import sys
sys.path.insert(0, '.')

from dashboard import calculate_threat_score
from datetime import datetime, timezone

with open('data/vouches.json', 'r') as f:
    data = json.load(f)

threats = []

for uid, record in data.items():
    if uid.isdigit():
        score = calculate_threat_score(data, uid)
        if score > 50:  # High threat
            threats.append((uid, score))

threats.sort(key=lambda x: x[1], reverse=True)

if threats:
    print(f"  Found {len(threats)} members with threat score > 50:")
    for uid, score in threats[:10]:
        print(f"    • User {uid}: {score}/100")
    if len(threats) > 10:
        print(f"    ... and {len(threats)-10} more")
else:
    print("  ✓ No high-threat members detected")
EOF
}

# ============================================================================
# MAIN COMMAND ROUTER
# ============================================================================

show_help() {
    cat << 'EOF'
Pve-Bot Maintenance Script

USAGE: ./maintenance.sh [command] [options]

BACKUP COMMANDS:
  backup              Create a backup of vouches.json
  restore <file>      Restore from a backup file
  list-backups        List all available backups

DATA COMMANDS:
  validate            Validate data file integrity
  optimize            Optimize storage (trim old data)
  cleanup             Clean up old log files
  stats               Show database statistics

MONITORING COMMANDS:
  health              Run all health checks
  audit               Run security threat audit

HELP:
  help                Show this help message

EXAMPLES:
  ./maintenance.sh backup
  ./maintenance.sh restore backups/vouches_20260901_120000.json.gz
  ./maintenance.sh health
  ./maintenance.sh audit

EOF
}

# Main router
main() {
    local command=${1:-help}

    case "$command" in
        backup)
            backup_data
            ;;
        restore)
            restore_backup "$2"
            ;;
        list-backups)
            list_backups
            ;;
        validate)
            validate_data
            ;;
        optimize)
            optimize_storage
            ;;
        cleanup)
            cleanup_old_logs
            ;;
        stats)
            show_stats
            ;;
        health)
            check_health
            ;;
        audit)
            audit_threats
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            log_error "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
