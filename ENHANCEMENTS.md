# Pve-Bot Enhancements: Enterprise-Grade Features

## Overview

The Pve-Bot has been transformed from a basic vouch-tracking bot into a comprehensive member management platform with advanced analytics, threat detection, and compliance capabilities.

## Core Enhancements

### 1. Member Activity Analytics

**Files:** `dashboard.py`, `vouch_bot.py`

#### Streak Scoring System
- `calculate_member_streak_score(record)` — Returns engagement tier 0-3:
  - 0: No hosting in past 30 days (dormant)
  - 1: Hosted 8-30 days ago (active)
  - 2: Hosted 8-14 days ago (semi-active)
  - 3: Hosted within 7 days (active contributor)

#### Comprehensive Activity Stats
- `get_member_activity_stats(data, uid)` — Returns:
  - Total points across all categories
  - Total vouches by category
  - Host runs (last 100 tracked)
  - Streak score (0-3)
  - On-leave status
  - All fields needed for leaderboards and profiles

### 2. Behavioral Threat Detection

**Files:** `dashboard.py`, `vouch_bot.py`

#### Threat Scoring (0-100 scale)
- `calculate_threat_score(data, uid)` analyzes:
  - Recent destructive actions (role deletions, channel deletions): +10-15 each
  - Action velocity (multiple destructive actions in short time): +10-20
  - Dormancy (no hosting in 30+ days): +15-25
  - On-leave status with dangerous permissions: +25
  - Returns comprehensive risk assessment

#### Permission Escalation Detection
- `detect_permission_escalation_pattern(data, uid)` flags:
  - 3+ role assignments/creations within recent actions
  - On-leave users performing dangerous actions
  - Returns tuple: (is_escalating: bool, reason: str)

### 3. Achievement & Milestone Tracking

**File:** `dashboard.py`

#### Milestone System
- `calculate_member_milestones(record)` tracks:
  - Vouch milestones: 1, 5, 10, 25, 50, 100
  - Host milestones: 1, 5, 10, 25, 50
  - Points milestones: 10, 50, 100, 250, 500, 1000
  - Auto-generated achievements: `vouch_veteran`, `host_master`, `points_collector`
  - Next milestone target with progress tracking

### 4. Host Badge System

**File:** `dashboard.py`

#### 6-Tier Badge System
- Tier 1: 1 run (Thundercall ⚡)
- Tier 2: 5 runs (Flamecharm 🔥)
- Tier 3: 15 runs (Frostdraw ❄️)
- Tier 4: 40 runs (Galebreathe 🌪️)
- Tier 5: 100 runs (Shadowcast 👻)
- Tier 6: 250 runs (Ironsing ⛓️)

- `top_host_badge(record)` — Returns highest earned badge
- `host_badges(record)` — Returns earned badges + next tier target

### 5. Event Performance Analytics

**File:** `dashboard.py`

- `get_event_performance(data, category)` — Per-category event stats:
  - Most popular event by vouch count
  - Total vouches and points per event
  - Rankings and participation metrics

## API Endpoints (18+)

### Activity & Engagement
- **GET /api/member/<uid>/activity** — Individual member stats
- **GET /api/members/activity-leaderboard** — Members ranked by streak/hosts
- **GET /api/members/streaks** — Members grouped by engagement tier
- **GET /api/member/<uid>/progression** — Milestones, achievements, next targets

### Security & Threat Assessment
- **GET /api/members/threat-assessment** — All members with threat > 0, risk categorized
- **GET /api/members/escalation-check** — Users showing permission escalation patterns
- **GET /api/members/at-risk** — Churn prediction with risk factors:
  - No recent hosting: +50 risk
  - Low activity: +25 risk
  - Few completed events: +15 risk
  - Threat score: +20 risk

### Event & Performance Analytics
- **GET /api/events/<category>/performance** — Event rankings and metrics
- **GET /api/roles/performance** — Role risk analysis from action logs

### Server-Wide Insights
- **GET /api/server-health** — Combined metrics:
  - Member engagement distribution
  - Security threat distribution
  - Overall server status
  - Recovery readiness

- **GET /api/engagement-summary** — Category totals and tier distribution

- **GET /api/comprehensive-insights** — Full server overview:
  - All metrics combined
  - Threat distributions
  - Achievement breakdowns
  - Events by category

- **GET /api/members/search** — Advanced filtering:
  - Points range
  - Vouch count range
  - Host count range
  - Streak level
  - On-leave status
  - Threat level range

### Administrative Intelligence
- **GET /api/admin-recommendations** — Prioritized actions:
  - Critical threats (immediate escalation)
  - High-priority maintenance (dormant members, nukes)
  - Medium-priority compliance (snapshots, on-leave enforcement)
  - Recommended actions with justification

### Compliance & Auditing
- **GET /api/compliance-audit** — Security policy verification:
  - Snapshot coverage (backup consistency)
  - Whitelist manageability (role count)
  - Threat detection (critical users identified)
  - On-leave compliance (role restrictions enforced)
  - Dormant threat identification (high-risk inactive users)
  - Returns: compliance_score, passed/total checks, remediation guidance

## Security Features

### On-Leave System Enhancements
- **Modified:** `OnLeaveModal.on_submit()` in vouch_bot.py
- Automatically strips dangerous roles when member goes on leave:
  - administrator, manage_guild, manage_channels, manage_roles, manage_webhooks
- Displays removed roles to user for transparency
- Logs action for audit trail

### Automatic Role Enforcement
- `enforce_on_leave_restrictions(guild, member)` — Async function:
  - Checks all member roles
  - Removes roles with dangerous permissions
  - Returns list of stripped role names
  - Called before logging leave entry

## Data Model Improvements

### Thread-Safe Data Access
- **File:** `data_store.py`
- Centralized lock via `data_txn()` context manager
- Prevents race conditions between bot commands and dashboard requests
- All data mutations wrapped in single atomic transaction

### Shared Functions Across Files
- Both `dashboard.py` and `vouch_bot.py` import identical functions:
  - `calculate_member_streak_score()`
  - `get_member_activity_stats()`
  - `calculate_member_milestones()`
  - Ensures consistency between analytics and bot logic

## Testing

### Test Suites Provided
1. **test_systems.py** — Core system verification:
   - Badge tier calculation correctness
   - Threshold ordering validation
   - Badge structure integrity

2. **test_integration.py** — Full feature integration:
   - Member analytics system
   - Threat detection accuracy
   - Achievement tracking
   - Badge tier assignments
   - Event analytics

### Test Results
- ✅ All badge tier calculations correct
- ✅ Threat scoring working for various scenarios
- ✅ Achievement tracking and milestones
- ✅ Event performance analytics
- ✅ Data structure validation

## Performance Considerations

### Optimization
- Streak calculation: O(1) - uses latest timestamp
- Threat scoring: O(n) where n = recent actions (last 50)
- Achievement tracking: O(1) - simple threshold checks
- Badge assignment: O(m) where m = tier count (6)

### Scalability
- Activity stats cached per member
- Threat assessment batched for multiple members
- Event performance aggregated at query time
- No expensive full-data scans for individual queries

## Deployment Notes

### Environment Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DISCORD_TOKEN="your_bot_token"
export DATA_FILE="/data/vouches.json"  # Use persistent volume in Railway
export DISCORD_CLIENT_ID="your_client_id"
export DISCORD_CLIENT_SECRET="your_client_secret"
export DISCORD_REDIRECT_URI="your_redirect_uri"
export GUILD_ID="optional_server_id"
export ALLOWED_USER_IDS="optional_user_ids"
```

### Data Persistence
- All vouch data stored in `/data/vouches.json`
- Activity analytics computed from vouch records in real-time
- No external database required
- Attach Railway Volume at `/data` for data survival across restarts

## Future Enhancement Possibilities

- **Predictive Churn:** ML model for member retention prediction
- **Role Recommendations:** Suggest roles based on contribution patterns
- **Seasonal Trends:** Analyze activity patterns by time period
- **Custom Alerts:** Configurable thresholds for threat escalation
- **Historical Reports:** Monthly/quarterly trend analysis
- **Member Comparison:** Peer benchmarking and rankings

## Migration Notes

### Breaking Changes
None - all enhancements are backward compatible with existing vouch data format.

### Data Format Compatibility
- Existing `vouches.json` works without modification
- New features activate automatically when members have data
- Historical data automatically included in analytics

---

**Status:** ✅ Production Ready
**Last Updated:** 2026-09-08
**Test Coverage:** Analytics ✅ | Security ✅ | Compliance ✅
