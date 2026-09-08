# Pve-Bot REST API Reference

Base URL: `http://localhost:5000/api` (development) or `https://your-domain.com/api` (production)

## Authentication

All endpoints except `/health` require authorization:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" https://api.example.com/api/endpoint
```

Set `DASHBOARD_SECRET` environment variable for token generation.

---

## Activity & Engagement Endpoints

### GET /member/{uid}/activity

Get comprehensive activity stats for a single member.

**Parameters:**
- `uid` (path, required): Discord user ID

**Response:**
```json
{
  "uid": "123456789",
  "total_points": 220,
  "total_vouches": 14,
  "host_runs": 5,
  "host_total": 42,
  "streak_score": 3,
  "on_leave": false,
  "badges": {
    "earned": [
      {"threshold": 1, "name": "Thundercall"},
      {"threshold": 5, "name": "Flamecharm"}
    ],
    "top": {"threshold": 40, "name": "Galebreathe", "icon": "galebreathe"},
    "next": {"threshold": 100, "name": "Shadowcast", "remaining": 58}
  }
}
```

**Status Codes:**
- `200` - Success
- `404` - Member not found
- `401` - Unauthorized

---

### GET /members/activity-leaderboard

Get members ranked by engagement metrics.

**Query Parameters:**
- `limit` (int, default: 50): Number of results (max 100)
- `offset` (int, default: 0): Pagination offset
- `sort_by` (string, default: "host_total"): Sort field - `host_total`, `streak_score`, `total_points`

**Response:**
```json
{
  "total": 847,
  "limit": 50,
  "offset": 0,
  "members": [
    {
      "rank": 1,
      "uid": "123456789",
      "username": "Aiko_Chan",
      "host_total": 342,
      "streak": 3,
      "points": 2150,
      "badge": {"icon": "ironsing", "name": "Ironsing"}
    }
  ]
}
```

---

### GET /members/streaks

Get members grouped by engagement tier.

**Response:**
```json
{
  "active": {
    "count": 342,
    "description": "Hosted in last 7 days",
    "members": [...]
  },
  "semi_active": {
    "count": 241,
    "description": "Hosted 8-14 days ago",
    "members": [...]
  },
  "inactive": {
    "count": 161,
    "description": "Hosted 15-30 days ago",
    "members": [...]
  },
  "dormant": {
    "count": 103,
    "description": "No hosting in 30+ days",
    "members": [...]
  }
}
```

---

### GET /member/{uid}/progression

Get member's achievements, milestones, and progression.

**Response:**
```json
{
  "uid": "123456789",
  "achievements": ["vouch_veteran", "host_master", "points_collector"],
  "vouches_milestone": {
    "current": 14,
    "next": 25,
    "progress": 56
  },
  "hosts_milestone": {
    "current": 42,
    "next": 50,
    "progress": 84
  },
  "points_milestone": {
    "current": 220,
    "next": 250,
    "progress": 88
  }
}
```

---

## Security & Threat Assessment

### GET /members/threat-assessment

Get all members with non-zero threat scores, categorized by severity.

**Response:**
```json
{
  "total_threatened": 12,
  "critical": [
    {
      "uid": "847291",
      "threat_score": 78,
      "reason": "Dormant 45+ days + destructive actions",
      "flags": ["dormant", "dangerous_actions", "escalation_pattern"],
      "actions": [
        "Review permissions",
        "Send warning message",
        "Consider soft suspension"
      ]
    }
  ],
  "high": [...],
  "medium": [...]
}
```

**Threat Score Ranges:**
- 0-30: Low risk
- 31-60: Medium risk
- 61-100: High risk (critical)

---

### GET /members/escalation-check

Detect members showing permission escalation patterns.

**Response:**
```json
{
  "escalating": [
    {
      "uid": "562018",
      "pattern": "role_assignments",
      "actions": 5,
      "timeframe": "48 hours",
      "alert": "3+ role assignments in recent actions",
      "recommendation": "Monitor for next 7 days"
    }
  ],
  "on_leave_with_perms": [
    {
      "uid": "293847",
      "on_leave_since": "2026-09-01T12:00:00Z",
      "dangerous_roles": ["administrator", "manage_guild"],
      "recommendation": "Force role enforcement"
    }
  ]
}
```

---

### GET /members/at-risk

Predict members at risk of churn.

**Response:**
```json
{
  "at_risk": [
    {
      "uid": "456123",
      "risk_score": 72,
      "factors": {
        "no_recent_hosting": 50,
        "low_activity": 25,
        "few_events": 15,
        "threat_score": 20
      },
      "last_activity": "2026-08-01T14:30:00Z",
      "days_inactive": 38,
      "recommendation": "Re-engagement campaign recommended"
    }
  ]
}
```

---

## Event & Performance Analytics

### GET /events/{category}/performance

Get performance metrics for a specific event category.

**Parameters:**
- `category` (path, required): `pve`, `security`, or `support`

**Response:**
```json
{
  "category": "pve",
  "total_vouches": 4231,
  "total_points": 8432,
  "events": [
    {
      "name": "Hellmode",
      "rank": 1,
      "vouches": 1250,
      "points": 18750,
      "participants": 342
    }
  ],
  "most_popular": "Hellmode",
  "trending_up": ["Deep Champion"],
  "trending_down": ["Elder"]
}
```

---

### GET /roles/performance

Analyze role risk and performance.

**Response:**
```json
{
  "roles": [
    {
      "name": "Master Hoster",
      "members": 45,
      "avg_threat_score": 12,
      "actions_logged": 340,
      "deletions": 2,
      "risk_level": "low"
    }
  ],
  "high_risk_roles": [
    {
      "name": "Moderator",
      "members": 8,
      "avg_threat_score": 45,
      "recommendation": "Review role assignments"
    }
  ]
}
```

---

## Server-Wide Insights

### GET /server-health

Get comprehensive server health metrics.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-09-08T15:30:00Z",
  "engagement": {
    "active": 342,
    "semi_active": 241,
    "inactive": 161,
    "dormant": 103,
    "average_score": 2.1
  },
  "security": {
    "total_threats": 12,
    "critical": 2,
    "high": 4,
    "medium": 6,
    "threat_trend": "stable"
  },
  "compliance": {
    "score": 98,
    "passed": 5,
    "total": 5,
    "issues": []
  },
  "recovery_readiness": {
    "backup_status": "recent",
    "data_integrity": "verified",
    "restore_time_minutes": 5
  }
}
```

---

### GET /engagement-summary

Get engagement metrics by category.

**Response:**
```json
{
  "categories": {
    "pve": {
      "total_points": 34000,
      "total_vouches": 8500,
      "unique_participants": 542
    },
    "security": {
      "total_points": 8200,
      "total_vouches": 4100
    },
    "support": {
      "total_points": 3030,
      "total_vouches": 1247
    }
  },
  "tier_distribution": {
    "active": 342,
    "semi_active": 241,
    "inactive": 161,
    "dormant": 103
  }
}
```

---

### GET /comprehensive-insights

Full server overview combining all metrics.

**Response:**
```json
{
  "snapshot_time": "2026-09-08T15:30:00Z",
  "members": {
    "total": 847,
    "active_this_week": 342,
    "new_this_month": 24
  },
  "achievements": {
    "vouch_veteran": 12,
    "host_master": 8,
    "points_collector": 5
  },
  "threat_distribution": {
    "critical": 2,
    "high": 4,
    "medium": 6,
    "low": 15
  },
  "events_by_category": {
    "pve": {"total": 8500, "most_popular": "Hellmode"},
    "security": {"total": 4100, "most_popular": "Security Vouch"},
    "support": {"total": 1247, "most_popular": "Backup Vouch"}
  }
}
```

---

## Advanced Queries

### GET /members/search

Advanced member search with filtering.

**Query Parameters:**
- `points_min` (int): Minimum total points
- `points_max` (int): Maximum total points
- `vouches_min` (int): Minimum vouch count
- `vouches_max` (int): Maximum vouch count
- `hosts_min` (int): Minimum host count
- `hosts_max` (int): Maximum host count
- `streak` (int): Exact streak score (0-3)
- `on_leave` (bool): Filter by on-leave status
- `threat_min` (int): Minimum threat score
- `threat_max` (int): Maximum threat score
- `limit` (int, default: 50): Results limit
- `offset` (int, default: 0): Pagination

**Example:**
```bash
GET /members/search?points_min=100&points_max=500&streak=3&limit=100
```

**Response:**
```json
{
  "query": {...},
  "total": 156,
  "results": [...]
}
```

---

## Compliance & Auditing

### GET /compliance-audit

Run security policy verification audit.

**Response:**
```json
{
  "compliance_score": 98,
  "timestamp": "2026-09-08T15:30:00Z",
  "checks": [
    {
      "name": "Snapshot Coverage",
      "status": "passed",
      "details": "Backups verified for last 30 days"
    },
    {
      "name": "Whitelist Manageability",
      "status": "passed",
      "details": "Role count: 47 (acceptable)"
    },
    {
      "name": "Critical Threat Detection",
      "status": "passed",
      "details": "2 critical threats identified and logged"
    },
    {
      "name": "On-Leave Compliance",
      "status": "passed",
      "details": "All on-leave members have dangerous roles stripped"
    },
    {
      "name": "Dormant Threat Identification",
      "status": "warning",
      "details": "7 dormant members with threat score > 40"
    }
  ],
  "recommendations": [
    "Review 7 dormant high-threat members",
    "Update role hierarchy documentation"
  ]
}
```

---

## Admin Operations

### GET /admin-recommendations

Get prioritized administrative actions.

**Response:**
```json
{
  "critical": [
    {
      "action": "Review high-threat user",
      "uid": "847291",
      "reason": "Threat score 78/100",
      "steps": ["Review permissions", "Send message", "Consider suspension"]
    }
  ],
  "high": [
    {
      "action": "Enforce on-leave restrictions",
      "uid": "293847",
      "reason": "On-leave with dangerous permissions"
    }
  ],
  "medium": [
    {
      "action": "Archive dormant member",
      "uid": "456789",
      "reason": "No activity for 90 days"
    }
  ]
}
```

---

## Error Responses

### 400 Bad Request
```json
{
  "error": "Invalid parameter",
  "message": "streak must be between 0 and 3",
  "field": "streak"
}
```

### 401 Unauthorized
```json
{
  "error": "Authentication failed",
  "message": "Invalid or missing authorization token"
}
```

### 404 Not Found
```json
{
  "error": "Member not found",
  "uid": "999999999"
}
```

### 500 Server Error
```json
{
  "error": "Internal server error",
  "message": "Database connection failed",
  "request_id": "abc123def456"
}
```

---

## Rate Limiting

- 100 requests per minute per IP
- 1000 requests per hour per token
- Burst: 10 requests per second

Response headers:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1694177400
```

---

## Pagination

List endpoints support pagination:

```bash
GET /members/activity-leaderboard?limit=50&offset=50
```

Response includes:
```json
{
  "total": 847,
  "limit": 50,
  "offset": 50,
  "has_more": true,
  "members": [...]
}
```

---

## Changelog

### v2.0.0 (2026-09-08)
- Added comprehensive analytics endpoints
- Added threat assessment and security endpoints
- Added compliance auditing
- Added admin recommendations

### v1.5.0 (2026-08-15)
- Added engagement summary
- Added role performance analytics

### v1.0.0 (2026-08-01)
- Initial API release

---

**Last Updated:** 2026-09-08
**API Version:** 2.0.0
**Support:** See ENHANCEMENTS.md for feature details
