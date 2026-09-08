# Pve-Bot Deployment & Operations Guide

## Quick Start (5 minutes)

### Prerequisites
- Python 3.9+
- Discord Bot Token
- Server with Manage Server permissions
- (Optional) Railway account for hosting

### Local Development Setup

```bash
# Clone repository
git clone https://github.com/Yuki-Onnaa/Pve-Bot.git
cd Pve-Bot

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DISCORD_TOKEN="your_bot_token_here"
export DATA_FILE="./data/vouches.json"

# Run the bot
python vouch_bot.py
```

Bot will start and connect to Discord. Use `?help` in any channel to see available commands.

---

## Production Deployment (Railway)

### Step 1: Create Railway Project

1. Go to [railway.app](https://railway.app)
2. Click "New Project" → "Deploy from GitHub"
3. Select your Pve-Bot repository fork
4. Railway auto-detects Python and creates deployment

### Step 2: Configure Environment

In Railway dashboard, set these variables:

```
DISCORD_TOKEN=your_bot_token
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
DISCORD_REDIRECT_URI=https://your-domain.com/callback
DATA_FILE=/data/vouches.json
GUILD_ID=your_server_id (optional)
ALLOWED_USER_IDS=user1,user2 (optional)
DASHBOARD_SECRET=random_secret_key
COOKIE_SECURE=1
NVIDIA_API_KEY=your_nvidia_key (for chat features)
```

### Step 3: Attach Persistent Volume

1. In Railway: Service → ⋯ menu → "Attach Volume"
2. Mount at: `/data`
3. Size: 5GB (grows as needed)

**Why:** Without this, `vouches.json` gets wiped on every deploy. The Volume persists data across restarts and updates.

### Step 4: Deploy

```bash
git push origin main
```

Railway auto-deploys on push. Monitor in Railway dashboard.

---

## Database & Storage

### Data Structure (`vouches.json`)

```json
{
  "123456789": {
    "pve": {
      "total_points": 125,
      "total_vouches": 8,
      "events": {"Hellmode": 5, "Titus": 3},
      "cooldowns": {"Hellmode": "2026-09-08T15:30:00+00:00"}
    },
    "security": {...},
    "support": {...},
    "host_runs": ["2026-09-08T14:00:00+00:00", ...],
    "host_runs_total": 42,
    "log": [
      {"action": "vouch", "category": "pve", "event": "Hellmode", "count": 1, ...}
    ]
  }
}
```

### Backup Strategy

**Automatic (Recommended):**
- Railway Volume auto-backs up daily
- Snapshots retained for 30 days
- One-click restore in Railway dashboard

**Manual Backup:**
```bash
# Download vouches.json
railway run cat /data/vouches.json > backup_$(date +%Y%m%d_%H%M%S).json

# Upload to safe location (GitHub Gists, Google Drive, etc.)
```

### Recovery Procedures

**Data Corruption:**
```bash
# Restore from Railway backup
railway postgres:restore --version <snapshot-date>

# Or manually restore from backup file
railway run bash -c 'cat > /data/vouches.json' < backup_20260901_120000.json
```

**Full Wipe & Resync:**
```
1. Use ?syncvouches command (Manage Server permission required)
2. Bot scans entire vouch channel history and rebuilds database
3. Takes 5-10 minutes for typical server
```

---

## Configuration & Customization

### Channel IDs (in `vouch_bot.py`)

Update these to match your server's channel IDs:

```python
DEFAULT_CONFIG = {
    "pve_channel_id": 1529113596657799178,          # PVE vouch channel
    "security_channel_id": 1527834552150659103,    # Security vouch channel
    "support_channel_id": 1527834504658550924,     # Support vouch channel
    "live_leaderboard_channel_id": 1530286316628217906,
    "audit_log_channel_id": 1530317395669815438,
    "event_ping_channel_id": 1529142467658649640,  # Scheduled event pings
    "chime_in_channel_id": 1478405937080307806,    # Casual chat channel
    "updates_channel_id": 1532474881915097118,     # Bot updates log
}
```

**To find channel IDs:**
- Enable Developer Mode in Discord (Settings → Advanced)
- Right-click channel → "Copy Channel ID"

### Event Points (in `dashboard.py`)

Customize point values for each event:

```python
FALLBACK_EVENT_POINTS = {
    "pve": {
        "Hellmode": 15,
        "Deep Champion": 15,
        "Enmity": 1.5,
        # Add custom events here
    },
    "security": {...},
    "support": {...},
}
```

### Rank Roles & Thresholds

**PVE Host Ranks (in `vouch_bot.py`):**
```python
RANKS = [
    ("Apprentice Hoster", 0),
    ("Skilled Hoster", 150),
    ("Master Hoster", 350),
    ("Divine Hoster", 750),
    ("Godlike Hoster", 1250),
    ("True Hoster", 2000),
    ("No Life Hoster", 3500),
    ("Absolute Being", 5000),
]
```

Update roles to match server; bot only assigns existing roles.

### Event Ping Schedule

**Modify in `vouch_bot.py`:**

```python
EVENT_PING_SCHEDULE = {
    "Carnival of Hearts": ["07:00", "08:30", "10:00", ...],
    "Interluminary Parasol": [...],
    "Battle Royale": [...],
}

EVENT_PING_TZ = "Africa/Tripoli"  # Change timezone
EVENT_PING_CHANNEL_ID = 1529142467658649640
```

---

## Performance Optimization

### Database Query Tuning

**For 10K+ members:**

```python
# In dashboard.py, batch member processing:
def get_all_threats_optimized(data, batch_size=100):
    """Process members in batches to avoid memory spikes"""
    members = [(uid, rec) for uid, rec in data.items() if uid.isdigit()]
    
    for i in range(0, len(members), batch_size):
        batch = members[i:i+batch_size]
        yield from process_batch(batch)
```

### Caching Strategy

```python
# Add to dashboard.py:
from functools import lru_cache
from datetime import datetime, timedelta

_cache_time = {}

@lru_cache(maxsize=100)
def cached_threat_assessment(uid_tuple, timestamp):
    """Cache threat scores for 5 minutes"""
    return calculate_threat_score(dict(uid_tuple), uid_tuple[0])

def get_threat_cached(data, uid):
    now = datetime.now()
    cache_key = (uid, now // timedelta(minutes=5))
    if cache_key not in _cache_time:
        _cache_time[cache_key] = cached_threat_assessment(tuple(data[uid].items()), now)
    return _cache_time[cache_key]
```

### Memory Optimization

- Limit `host_runs` to last 100 entries (already done)
- Archive old logs quarterly
- Use pagination for API endpoints (max 50 items/page)

---

## Monitoring & Alerting

### Health Checks

Set up external monitoring to ping bot every 5 minutes:

```bash
# Check if bot is responding
curl -s http://localhost:5000/health && echo "✓ Bot healthy" || echo "✗ Bot offline"
```

Add to `vouch_bot.py`:

```python
@app.route('/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'bot_ready': bot.is_ready(),
    })
```

### Log Monitoring

**Watch bot.log for errors:**
```bash
tail -f bot.log | grep ERROR

# Alert on specific errors
tail -f bot.log | grep -E "CRITICAL|FATAL" | while read line; do
    # Send alert (webhook, email, etc.)
    curl -X POST https://hooks.slack.com/... -d "alert: $line"
done
```

### Performance Metrics

Monitor these metrics weekly:

- **Response time:** API endpoints should respond in <500ms
- **Error rate:** Should be <0.1%
- **Memory usage:** Should not exceed 500MB
- **Data file size:** Should not exceed 100MB

```bash
# Check current metrics
du -sh /data/vouches.json
ps aux | grep vouch_bot | grep -v grep | awk '{print "Memory:", $6/1024 "MB"}'
```

---

## Maintenance Schedule

### Daily
- Monitor threat assessments
- Check audit log for suspicious activity

### Weekly
- Review `/api/admin-recommendations`
- Backup vouch data (automatic)
- Check bot uptime status

### Monthly
- Generate compliance audit report: `/api/compliance-audit`
- Archive old audit logs
- Review and update event points as needed
- Test disaster recovery procedure

### Quarterly
- Archive historical data older than 6 months
- Update role thresholds based on member growth
- Review and optimize database queries
- Update documentation

---

## Troubleshooting

### Bot Won't Start

```bash
# Check Python version
python3 --version  # Must be 3.9+

# Check dependencies
pip install -r requirements.txt --upgrade

# Check Discord token
echo $DISCORD_TOKEN  # Should print token

# Run with verbose output
python vouch_bot.py --verbose
```

### Data Not Persisting

```bash
# Check volume is mounted
railway run mount  # Should show /data

# Check permissions
railway run ls -la /data/

# Force data save
# Send ?syncvouches in Discord to rebuild from history
```

### Dashboard API 500 Errors

```bash
# Check data file format
python3 -c "import json; json.load(open('/data/vouches.json'))"

# Check for missing fields
railway run python3 -c "
import json
data = json.load(open('/data/vouches.json'))
for uid, rec in data.items():
    if 'host_runs' not in rec: print(f'Missing host_runs: {uid}')
"
```

### High Memory Usage

```bash
# Check for memory leaks
ps aux | grep vouch_bot

# Restart bot
railway redeploy

# Or: kill and restart
railway run pkill -f vouch_bot
```

---

## API Integration Examples

### Get Member Stats

```bash
curl -X GET "http://localhost:5000/api/member/123456789/activity" \
  -H "Authorization: Bearer YOUR_AUTH_TOKEN"
```

### Get Threat Assessment

```bash
curl -X GET "http://localhost:5000/api/members/threat-assessment" \
  -H "Authorization: Bearer YOUR_AUTH_TOKEN"
```

### Export Leaderboard

```bash
curl -X GET "http://localhost:5000/api/members/activity-leaderboard?limit=100" \
  > leaderboard.json
```

---

## Scaling Guidelines

| Members | Recommended | Memory | Storage |
|---------|------------|--------|---------|
| <1K | Local dev | 256MB | 10MB |
| 1K-10K | Single Railway | 512MB | 50MB |
| 10K-50K | Railway + Cache | 1GB | 200MB |
| 50K+ | Multi-instance | 2GB | 500MB+ |

---

## Support & Documentation

- **Main README:** See `README.md` for command reference
- **Enhancements:** See `ENHANCEMENTS.md` for feature details
- **Admin Dashboard:** Open `ADMIN_DASHBOARD.html` in browser for visual overview
- **API Docs:** See `/api/docs` endpoint (when implemented)
- **Discord Server:** [link to support server]

---

**Last Updated:** 2026-09-08
**Maintained By:** Pve-Bot Development Team
**Version:** 2.0.0
