# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.0.x   | ✅ Yes             |
| 1.5.x   | ⚠️ Limited         |
| < 1.5   | ❌ No              |

## Reporting a Vulnerability

**Do not open public issues for security vulnerabilities.**

Please report security issues to: **security@pvebot.dev**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if available)

You will receive a response within 48 hours. We request you keep the issue confidential until a patch is released.

## Security Practices

### Data Protection
- All sensitive data encrypted at rest and in transit
- Passwords and tokens never logged
- Discord OAuth2 for authentication
- Session cookies (HTTPONLY, SameSite)

### Access Control
- Role-based access (admin required for sensitive operations)
- API token authentication
- Rate limiting on all endpoints
- Permission verification on data access

### Threat Detection
- Behavioral threat scoring
- Permission escalation detection
- Dormant account monitoring
- Automated compliance auditing

### Regular Updates
- Security patches within 48 hours of discovery
- Quarterly dependency updates
- Monthly security audit
- Pre-commit security scanning

### Best Practices for Users

1. **Keep tokens secure:**
   - Never share bot token publicly
   - Rotate token if compromised
   - Use environment variables, not hardcoded

2. **Backup data regularly:**
   - Use `./maintenance.sh backup`
   - Store backups securely
   - Test restore procedures

3. **Monitor threats:**
   - Review threat assessment weekly
   - Check escalation patterns
   - Validate compliance audit

4. **Update promptly:**
   - Apply security patches immediately
   - Test in staging before production
   - Review changelog for breaking changes

## Known Vulnerabilities

None currently known. Report any discovered vulnerabilities per the process above.

## Security Headers

Production deployment includes:
```
Content-Security-Policy: default-src 'self'
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Strict-Transport-Security: max-age=31536000; includeSubDomains
```

## Dependency Security

- All dependencies scanned by Dependabot
- Automated PRs for security updates
- Manual review before merging
- Changelog notes security fixes

## Contact

- **Security Issues:** security@pvebot.dev
- **Bug Reports:** GitHub Issues
- **Questions:** GitHub Discussions
