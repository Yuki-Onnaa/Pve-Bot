# Pve-Bot Operations Runbook

Emergency procedures, common tasks, and step-by-step guides for server administrators.

---

## Emergency Procedures

### 🚨 Bot Not Responding

**Symptom:** Bot not responding to commands or slash commands failing

**Steps:**
1. Check if bot is online in Discord member list
2. Run health check:
   ```bash
   ./maintenance.sh health
   ```
3. Check bot logs for errors:
   ```bash
   tail -f bot.log | grep ERROR
   ```
4. **If offline:** Restart bot
   ```bash
   # In Railway
   railway redeploy
   
   # Or locally
   pkill -f vouch_bot
   python vouch_bot.py &
   ```
5. Wait 30 seconds for reconnection
6. Test with `?help` command

**If still not working:**
- Check Discord token is valid
- Verify bot has required permissions in server
- Check internet connection

---

### 🚨 Data Corruption Detected

**Symptom:** Bot crashes on startup with JSON parse error

**Steps:**
1. **DO NOT RESTART** - creates risk of further damage
2. Backup current corrupted file:
   ```bash
   cp data/vouches.json data/vouches_corrupted.json
   ```
3. Try automatic repair:
   ```bash
   python3 << 'EOF'
   import json
   
   try:
       with open('data/vouches.json', 'r') as f:
           json.load(f)
   except json.JSONDecodeError as e:
       print(f"Error at position {e.pos}: {e.msg}")
       # Restore from backup
       import shutil
       shutil.copy('backups/vouches_YYYYMMDD_HHMMSS.json.gz', 'data/vouches.json')
   EOF
   ```
4. If no recent backup:
   ```bash
   # Rebuild from Discord history (takes 5-10 min)
   python vouch_bot.py  # Bot will auto-sync when started
   # Then in Discord: ?syncvouches (requires Manage Server)
   ```
5. Verify data:
   ```bash
   ./maintenance.sh validate
   ```

---

### 🚨 High Disk Usage

**Symptom:** "No space left on device" error

**Steps:**
1. Check disk usage:
   ```bash
   df -h /data
   ```
2. List largest files:
   ```bash
   du -sh /data/* | sort -h
   ```
3. **Clean up:**
   ```bash
   # Option A: Archive old backups
   find /data/backups -name "*.gz" -mtime +30 -delete
   
   # Option B: Compress backup storage
   tar -czf /data/backups_archive.tar.gz /data/backups/
   rm -rf /data/backups/
   
   # Option C: Optimize database
   ./maintenance.sh optimize
   ```
4. Verify space:
   ```bash
   df -h /data
   ```

---

### 🚨 Members Missing from Database

**Symptom:** Member stats show as 0 even though they have vouches

**Steps:**
1. Check if member is in database:
   ```bash
   python3 -c "import json; data=json.load(open('data/vouches.json')); print('123456789' in data)"
   ```
2. If missing, resync from Discord history:
   ```bash
   # In Discord with Manage Server permission:
   ?syncvouches
   ```
3. Wait for completion (appears in audit log)
4. Verify member record:
   ```bash
   python3 << 'EOF'
   import json
   data = json.load(open('data/vouches.json'))
   uid = '123456789'
   if uid in data:
       print(f"User points: {sum(data[uid].get(cat, {}).get('total_points', 0) for cat in ['pve', 'security', 'support'])}")
   EOF
   ```

---

## Daily Maintenance

### Morning Checklist (5 min)

- [ ] Verify bot is online
  ```bash
  curl -s http://localhost:5000/health
  ```
- [ ] Check error logs
  ```bash
  grep ERROR bot.log | tail -5
  ```
- [ ] Review threat assessment
  ```bash
  # Check /api/members/threat-assessment in dashboard
  ```
- [ ] Confirm backup ran
  ```bash
  ls -lh backups/ | head -3
  ```

### End of Day Checklist (5 min)

- [ ] Review audit log entries (check for unusual activity)
- [ ] Validate data integrity
  ```bash
  ./maintenance.sh validate
  ```
- [ ] Create manual backup
  ```bash
  ./maintenance.sh backup
  ```

---

## Weekly Procedures

### Monday - Capacity Review (15 min)

```bash
# Check database size and growth
du -sh /data/vouches.json

# Check member count
python3 << 'EOF'
import json
data = json.load(open('data/vouches.json'))
users = sum(1 for uid in data if uid.isdigit())
print(f"Total members: {users}")
EOF

# Check backups retention
ls -lh backups/ | wc -l
```

### Wednesday - Security Audit (20 min)

```bash
# Run threat assessment
./maintenance.sh audit

# Check escalation patterns via API
curl -X GET "http://localhost:5000/api/members/escalation-check"

# Review admin recommendations
curl -X GET "http://localhost:5000/api/admin-recommendations"
```

### Friday - Compliance Check (15 min)

```bash
# Run compliance audit
curl -X GET "http://localhost:5000/api/compliance-audit"

# Verify on-leave enforcement
python3 << 'EOF'
import json
data = json.load(open('data/vouches.json'))
on_leave = [uid for uid, rec in data.items() if uid.isdigit() and rec.get('on_leave')]
print(f"Members on leave: {len(on_leave)}")
EOF
```

---

## Monthly Procedures

### End of Month - Archive & Report (45 min)

1. **Generate monthly report:**
   ```bash
   curl -X GET "http://localhost:5000/api/comprehensive-insights" > monthly_report_$(date +%Y%m).json
   ```

2. **Archive old logs:**
   ```bash
   tar -czf logs_archive_$(date +%Y%m).tar.gz bot.log
   > bot.log  # Reset log file
   ```

3. **Clean old backups:**
   ```bash
   find backups/ -name "*.gz" -mtime +30 -delete
   ```

4. **Database optimization:**
   ```bash
   ./maintenance.sh optimize
   ```

5. **Full backup to external storage:**
   ```bash
   cp data/vouches.json /external-storage/vouches_$(date +%Y%m%d).json
   ```

6. **Generate statistics:**
   ```bash
   ./maintenance.sh stats
   ```

---

## Common Administrative Tasks

### Add New Admin/Moderator

1. Create role in Discord server
2. Set role permissions in Discord
3. Assign role to user
4. Verify permissions with role in audit log

**No database changes needed** - bot reads role assignments from Discord in real-time.

---

### Remove Member's Data

**⚠️ Permanent - Cannot be undone**

```bash
python3 << 'EOF'
import json

# Backup first
import shutil
shutil.copy('data/vouches.json', 'data/vouches_backup_before_delete.json')

# Load and delete
data = json.load(open('data/vouches.json'))
uid = '123456789'

if uid in data:
    del data[uid]
    with open('data/vouches.json', 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Deleted user {uid}")
else:
    print(f"User {uid} not found")
EOF
```

---

### Adjust Event Points

1. Open `dashboard.py`
2. Find `FALLBACK_EVENT_POINTS` section
3. Modify point values:
   ```python
   FALLBACK_EVENT_POINTS = {
       "pve": {
           "Hellmode": 15,  # ← Change this
           "Titus": 3,      # ← Or this
       },
   }
   ```
4. Save and restart bot
5. New vouches use new values; old vouches stay the same

---

### Update Rank Role Thresholds

1. Open `vouch_bot.py`
2. Find role threshold configuration
3. Update point thresholds:
   ```python
   RANKS = [
       ("Apprentice Hoster", 0),     # Everyone
       ("Skilled Hoster", 150),      # ← Adjust
       ("Master Hoster", 350),       # ← Adjust
   ]
   ```
4. Restart bot - automatic re-assignment happens on next vouch

---

### Ban Member (Prevent Vouches)

**Method 1: Discord Permissions**
- Remove member from server (nuclear option)
- Or remove vouch-channel view permissions

**Method 2: Soft Ban (Recommended)**
```bash
python3 << 'EOF'
import json

data = json.load(open('data/vouches.json'))
uid = '123456789'

# Mark as banned
if uid not in data:
    data[uid] = {}
data[uid]['banned_from_vouches'] = True
data[uid]['ban_reason'] = 'Abuse of vouch system'
data[uid]['ban_date'] = '2026-09-08T15:30:00Z'

with open('data/vouches.json', 'w') as f:
    json.dump(data, f, indent=2)
EOF
```

Then modify bot to check `banned_from_vouches` before accepting vouches.

---

### Manually Award Vouches (Backfill)

In Discord (Manage Server permission required):

```
?backfill pve @user "Hellmode" 5
?backfill security @user "Security Vouch" 3
?backfill support @user "Backup Vouch" 2
```

Bot logs all backfills in audit log with timestamp and reason.

---

## Monitoring & Alerting Setup

### Set Up Uptime Monitoring

Use external monitoring service (Uptime Robot, etc.):

```bash
# Health check endpoint
GET http://localhost:5000/health
# Returns 200 if healthy

# Expected response
{
  "status": "healthy",
  "bot_ready": true,
  "timestamp": "2026-09-08T15:30:00Z"
}
```

Alert thresholds:
- Down for 5+ minutes → Send Slack alert
- Error rate > 5% → Send warning

---

### Set Up Log Alerts

Monitor logs for critical errors:

```bash
# Create alert script
watch -n 60 'grep -c ERROR bot.log'

# Or use logrotate + rsyslog to aggregate
# Or send to centralized logging (ELK, Datadog, etc.)
```

Alert on:
- `CRITICAL` log level
- `Database connection failed`
- `JSON decode error`
- Authentication failures

---

## Performance Tuning

### Check Current Performance

```bash
# API response time
time curl -X GET "http://localhost:5000/api/members/activity-leaderboard"

# Database size
du -sh /data/vouches.json

# Memory usage
ps aux | grep vouch_bot | grep -v grep | awk '{print $6/1024 "MB"}'

# Disk I/O
iostat 1 5
```

### Optimize Slow Queries

**If threat assessment takes >2 seconds:**
```python
# Cache threat scores for 5 minutes
@lru_cache(maxsize=500)
def cached_threat_score(uid_hash, cache_time):
    return calculate_threat_score(uid, uid)
```

**If leaderboard takes >1 second:**
```python
# Pre-calculate and cache top 100
# Update only on new vouch, not on every request
```

---

## Disaster Recovery

### Recovery Time Objectives (RTO)
- **Unplanned outage:** 1 hour max
- **Data corruption:** 4 hours max (restore + verify)
- **Complete server loss:** 24 hours max

### Recovery Point Objective (RPO)
- **Data loss:** Max 6 hours (backups every 6 hours)
- **Configuration loss:** 0 hours (stored in git)

### Complete Server Failure Recovery

1. **Provision new Railway project** (5 min)
2. **Restore latest backup** (5 min)
   ```bash
   gunzip -c backups/vouches_latest.json.gz > data/vouches.json
   ```
3. **Verify data integrity** (5 min)
   ```bash
   ./maintenance.sh validate
   ```
4. **Run bot** (2 min for startup)
5. **Verify in Discord** (5 min - test commands)

**Total time:** ~25 minutes

---

## Documentation & Knowledge Base

### Where to Find Info

| Question | Resource |
|----------|----------|
| How to deploy? | DEPLOYMENT_GUIDE.md |
| What features exist? | ENHANCEMENTS.md |
| API endpoints? | API_REFERENCE.md |
| Bot commands? | README.md |
| This runbook? | OPERATIONS_RUNBOOK.md |

### Keeping Docs Updated

After any change:
1. Update relevant .md file
2. Commit with description
3. Push to repository
4. Link in Discord announcements

---

## Escalation Policy

### Level 1 (Yourself)
- Check health status
- Review logs
- Attempt restart
- Check admin recommendations

### Level 2 (Server Admin)
- Verify issue persists
- Provide logs and reproduction steps
- Ask in support channel
- Document for troubleshooting guide

### Level 3 (Developer)
- Provide full context and logs
- Include git commit hash of current deployment
- Attach sanitized database snapshot if possible

---

## Quick Reference

### Most Used Commands

```bash
# Create backup
./maintenance.sh backup

# Check health
./maintenance.sh health

# Validate data
./maintenance.sh validate

# View stats
./maintenance.sh stats

# Run audit
./maintenance.sh audit

# Restore backup
./maintenance.sh restore backups/vouches_YYYYMMDD_HHMMSS.json.gz
```

### Most Used APIs

```bash
# Get all threats
curl http://localhost:5000/api/members/threat-assessment

# Get recommendations
curl http://localhost:5000/api/admin-recommendations

# Get compliance score
curl http://localhost:5000/api/compliance-audit

# Get member stats
curl http://localhost:5000/api/member/123456789/activity

# Get leaderboard
curl http://localhost:5000/api/members/activity-leaderboard
```

---

**Last Updated:** 2026-09-08
**Version:** 2.0.0
**Maintained By:** Server Admin Team
