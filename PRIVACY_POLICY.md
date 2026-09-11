# Privacy Policy - Pve-Bot

**Last Updated:** September 11, 2026

## 1. Overview

Pve-Bot ("we", "us", "the Service") is committed to protecting your privacy. This policy explains what data we collect, how we use it, and your rights.

## 2. What Data We Collect

We collect and store:

### User Identifiers
- **Discord User ID** (required to track vouches)
- **Discord Username/Display Name** (for display purposes)
- **Server/Guild ID** (to organize data by server)

### Vouch Data
- **Vouch records** - Category, event type, count, points
- **Who vouched for you** (user ID of voucher)
- **When vouched** (timestamp)
- **Vouch comments/notes** (if provided)

### Behavioral Data
- **Threat scores** (calculated from vouches and behavior)
- **On-leave status** (duration, reason)
- **Role changes and removals**
- **Leaderboard positions**

### Server Management Data
- **Admin actions** (who added/removed vouches, when)
- **Audit logs** (changes to user data)
- **Server settings** (if customized)

### Technical Data
- **API requests** (timestamps, endpoints accessed)
- **Error logs** (for debugging)
- **IP addresses** (for infrastructure logging only, not tracked per user)

## 3. What We DON'T Collect

We explicitly do NOT collect:
- Passwords or authentication tokens
- Direct messages or private communication
- Payment information
- Location data
- Browsing history outside Discord
- Biometric data
- Sensitive personal information

## 4. How We Use Your Data

We use your data to:
- **Maintain vouch records** - Core functionality
- **Calculate leaderboards** - Ranking and statistics
- **Generate threat scores** - Behavioral analysis for server safety
- **Audit trails** - Track who modified what and when
- **Service improvement** - Fix bugs, optimize performance
- **Compliance** - Prevent abuse and enforce Terms of Service

We DO NOT:
- Sell your data to third parties
- Share data with advertisers
- Use data for marketing or profiling
- Combine data from multiple servers (kept separate)
- Track you across other websites

## 5. Data Storage & Security

### Where Data is Stored
- **Primary:** JSON file on deployment server (Railway)
- **Backup:** Encrypted backups if configured
- **Not cloud:** Data is not replicated to unknown cloud services

### Security Measures
- **File permissions:** Restricted access to data files
- **Encryption in transit:** HTTPS for all dashboard connections
- **No public access:** Data is not publicly accessible
- **Admin-only access:** Only server admins can view/modify

### What We Can't Guarantee
- We cannot guarantee data won't be lost (always keep backups)
- Compromised admin accounts = compromised data
- Bugs may cause unexpected data exposure
- Discord's security is outside our control

## 6. Server Admin Access

Server administrators with bot access can:
- View all user vouch data in their server
- Modify or delete vouch records
- Access audit logs
- See threat scores
- Configure bot settings

**Admins are responsible for protecting user privacy** - if your server misuses data, that's not our liability.

## 7. Data Retention

### How Long We Keep Data
- **Active servers:** While you're a member and the bot is active
- **Deleted records:** Permanently removed when admin deletes them
- **Inactive servers:** May be purged after extended inactivity
- **Bot removal:** Data is deleted when bot leaves the server

### Request Data Deletion
If you want your data deleted:
1. Ask your server admin to remove you from the bot
2. Admin can use `?` command to delete your records
3. Contact bot developers if admins don't cooperate

## 8. Third-Party Services

### Discord
- The bot uses Discord's API
- Discord collects data per their Privacy Policy
- We don't control Discord's data handling

### Railway (Hosting)
- Your data is hosted on Railway's servers
- Railway has access to server files
- See Railway's Privacy Policy for their practices

### GitHub
- Code and version history is on GitHub
- User data is NOT on GitHub
- See GitHub's Privacy Policy

## 9. Children's Privacy

This bot is not intended for children under 13. We don't knowingly collect data from children. If you're under 13, don't use this bot without parent permission.

## 10. Your Rights

You have the right to:
- **Access:** Ask your admin for your data
- **Correct:** Request inaccurate data be fixed
- **Delete:** Request your data be removed
- **Port:** Get your data in a readable format
- **Object:** Challenge how your data is used

Contact your server admin or bot developers to exercise these rights.

## 11. International Users

If you're outside the US, your data may be stored internationally. By using this bot, you consent to that transfer.

## 12. Changes to Policy

We may update this policy anytime. We'll notify users of major changes. Continued use = acceptance.

## 13. Disclosure of Data

We may disclose your data if:
- **Legal requirement** - Court order, law enforcement
- **Safety threat** - Imminent harm or abuse
- **ToS violation** - To enforce our Terms of Service
- **Admin request** - Server admins can access their data
- **Bot developers only** - No third-party access

## 14. Contact & Complaints

### Questions?
Contact the bot developers via:
- GitHub issues: https://github.com/Yuki-Onnaa/Pve-Bot/issues
- Discord server: [your Discord link]

### Complaints
If you believe we're mishandling your data:
1. Contact the server admin first
2. Contact bot developers with details
3. File a complaint with appropriate data protection authorities

## 15. CCPA & GDPR Notices

### California (CCPA)
If you're a California resident, you have additional rights under CCPA. Contact us for a data access request.

### Europe (GDPR)
If you're in the EU, your data is protected under GDPR. You have rights to access, correct, delete, and port your data.

## 16. Limitations

**Important:** We are not professional data handlers. This is a hobby/community bot. For sensitive operations, use professional services with guaranteed privacy.

---

**By using Pve-Bot, you accept this Privacy Policy.**

Last updated: September 11, 2026
