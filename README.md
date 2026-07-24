# Vouch Counter Discord Bot

Tracks three separate vouch categories, each in its own channel.

## PVE (channel: 1529113596657799178)

Format: `vouch @user1 @user2 ... <event>`

| Event              | Points |
|--------------------|--------|
| Enmity             | 1.5    |
| Elder              | 2      |
| Titus              | 3      |
| Hellmode           | 15     |
| Deep Champion      | 15     |
| Diluvian W (25)    | 3      |
| Diluvian W (50)    | 10     |
| Parasol            | 5      |
| Layer 2 (1)        | 3      |
| Layer 2 (2)        | 7      |
| Other Bosses       | 1      |

No cooldown — vouch as often as needed.

## Security (channel: 1527834552150659103)

Format: `<event> @user1 @user2 ...`

| Command                  | Points | Cooldown |
|---------------------------|--------|----------|
| `security vouch @user`    | 1      | 1 hour   |
| `depths vouch @user`      | 1.5    | 1 hour   |
| `defense vouch @user`     | 1      | none     |
| `depths defense vouch @user` | 1.5 | none     |

## Support (channel: 1527834504658550924)

Format: `<event> @user1 @user2 ...`

| Command                     | Points | Cooldown |
|-------------------------------|--------|----------|
| `support vouch @user`         | 1      | 1 hour   |
| `backup vouch @user`          | 2      | 1 hour   |
| `depths safe vouch @user`     | 5      | 1 hour   |

Cooldowns are per-target, per-event-type: if someone already received that
specific vouch type within the last hour, further vouches of that type for
them are skipped (bot reacts ⏳) until the cooldown clears. Defense-type
vouches have no cooldown, since multiple ganks can happen back to back.

## Reactions

Instead of replying with a message, the bot reacts on the vouch message:
- ✅ = at least one vouch recorded
- ⏳ = at least one target was skipped due to being on cooldown for that event
- 🚫 = you tried to vouch yourself (shown with ✅ if you also vouched others)
- ❌ = (PVE only) event type wasn't recognized

## Setup

1. Create a bot at https://discord.com/developers/applications
   - "Bot" tab → Add Bot
   - Turn ON **Message Content Intent**
   - Copy the bot token
2. Invite it with scope `bot` and permissions: Send Messages, Read Message
   History, View Channels, Add Reactions
3. `pip install -r requirements.txt`
4. Set your token: `export DISCORD_TOKEN="your_token_here"`
5. Run: `python vouch_bot.py`

## Commands

- `?vouches @user [pve|security|support]` — shows totals; with no category,
  shows a combined summary across all three
- `?profile [@user]` — a combined profile card showing total points, rank,
  and a progress bar toward the next rank for Host and Support (Security
  has no rank ladder, so it just shows points). Defaults to your own
  profile if no user is mentioned.
- `?leaderboard [n]` — Host (PVE) leaderboard
- `?sleaderboard [n]` — Security leaderboard
- `?suleaderboard [n]` — Support leaderboard
- `?addvouch <pve|security|support> @user <event> [count]` (alias `?backfill`)
  — manually records historical vouches. Requires Manage Server permission.
  Example: `?addvouch security "Security Vouch" 3`
- `?backfillhistory <pve|security|support> @user` — lists that user's recent
  backfill entries with their IDs, so you can find one to revert. Requires
  Manage Server permission.
- `?revertbackfill <pve|security|support> @user [log_id]` (alias
  `?undobackfill`) — undoes a backfilled vouch. Leave off `log_id` to
  revert the most recent backfill for that user/category, or pass an ID
  from `?backfillhistory` to revert a specific one. Requires Manage Server
  permission.
- `?syncvouches` (alias `?scanhistory`) — scans the full history of all
  three vouch channels and rebuilds all vouch data from scratch. Requires
  Manage Server permission. Run this after setup or whenever data resets.

## Live leaderboards

The bot automatically posts and maintains 3 live-updating leaderboard
embeds (Host, Security, Support) in channel `1530286316628217906`. They're
created the first time the bot starts up, and refresh automatically
whenever a new vouch is recorded — no need to keep running `?leaderboard`
manually. If those messages ever get deleted, just restart the bot and
they'll be recreated.

## Audit log

Every recorded vouch, backfill, and sync gets logged to channel
`1530317395669815438` — who vouched whom, for what, and how many points.
Useful for catching disputes or abuse after the fact.

## Auto rank roles

The bot automatically assigns a rank role based on total points, and
removes the previous rank when someone levels up. **The role names below
must already exist in your server exactly as written** (case-sensitive) —
the bot only assigns existing roles, it doesn't create them.

**Host (PVE) points:**
| Role              | Points |
|-------------------|--------|
| Apprentice Hoster  | 0      |
| Skilled Hoster     | 150    |
| Master Hoster      | 350    |
| Divine Hoster      | 750    |
| Godlike Hoster     | 1250   |
| True Hoster        | 2000   |
| No Life Hoster     | 3500   |
| Absolute Being     | 5000   |

**Support points:**
| Role                | Points |
|----------------------|--------|
| Guardian Link         | 0      |
| Vigor Warden          | 15     |
| Soul Reliefer         | 45     |
| Graceful Commander    | 100    |
| Hero Of Events        | 200    |

Security has no rank ladder configured yet — only Host and Support have
role rewards right now.

**Important:** the bot's own role in your server must be positioned
*above* all of these rank roles in Role Settings, and the bot needs
**Manage Roles** permission — otherwise Discord won't let it assign them,
and it'll post a warning in the audit log channel when that happens.

## Persistent storage (important)

Railway wipes its normal filesystem on every redeploy. Attach a **Volume**
mounted at `/data` (service → ⋯ menu → Attach volume) so `vouches.json`
survives redeploys and restarts. The bot already reads/writes there by
default. After attaching the volume, run `?syncvouches` once to recover any
history from before it was added.
