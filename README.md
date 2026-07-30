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

- `?postleaderboards` (alias `?refreshleaderboards`) — manually forces the
  3 live leaderboard embeds to post/refresh immediately, instead of waiting
  for a new vouch or a restart. Requires Manage Server permission.

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

## Chat with the bot

@mention the bot anywhere and it'll reply conversationally, remembering the
last several messages in that channel so you can have an actual back-and-forth.
It's built to feel like a member of the server rather than an assistant —
it doesn't lead with "how can I help," has opinions, and won't bring up
vouch tracking unless you actually ask about it.

It also occasionally jumps into conversation on its own — without being
@mentioned — in channel `1478405937080307806`, roughly once every 10-15
messages, reading the recent chat and chiming in like a regular member
would. This only happens in that one channel.

It automatically knows your real vouch totals (and anyone else's you
@mention alongside it), so you can ask things like "how many vouches do I
have" or "what's @Nico's total" and get an accurate answer pulled straight
from the vouch data — no guessing. If you ask about someone you didn't
@mention, it'll say it doesn't have their stats handy and point you to
`?vouches @user`.

You can also just ask for a leaderboard in chat — e.g. "show me the
security leaderboard" or "@bot leaderboard" — and it'll post the real
leaderboard embed directly (skipping the AI entirely for speed and
accuracy). Mention "security" or "support" to get that one; otherwise it
defaults to Host.

It does NOT have real knowledge of specific Deepwoken game mechanics
(exact stat requirements, talents, etc.) — it'll admit when it's unsure
instead of making things up rather than guess wrong.

- `?shutdown` (alias `?sleep`) — turns off @mention chat and the passive
  chime-ins. Vouch tracking, leaderboards, and everything else keeps
  working normally. Requires Manage Server permission. The setting
  persists across restarts.
- `?awake` (alias `?wakeup`) — turns chat back on. Requires Manage Server
  permission.
- `?persona <name>` — switches the bot's personality. Options: `default`,
  `hype`, `chill`, `sarcastic`, `formal`. Requires Manage Server permission.
- `?personas` — lists available personas and shows which one is active.

### Memory

The bot can permanently remember specific facts you teach it, surviving
restarts (stored alongside the vouch data, so make sure the persistent
Volume is set up — see below).

- `?addmemory <text>` (alias `?remember`) — teaches the bot something to
  remember permanently, e.g. `?addmemory Our server was founded in 2024`.
  Requires Manage Server permission.
- `?memories` — lists everything currently remembered, with IDs. Anyone
  can run this.
- `?removememory <id>` (alias `?forget`) — removes a specific memory by
  ID (get the ID from `?memories`). Requires Manage Server permission.

**Setup (free, no credit card):**
1. Go to https://build.nvidia.com and sign up (free NVIDIA Developer account)
2. Go to **API Keys** → **Generate API Key**
3. In Railway → Variables, add:
   - `NVIDIA_API_KEY` = the key you just generated
4. Redeploy

Uses `meta/llama-3.1-70b-instruct` by default — bigger and more capable
than the original 49B Nemotron, and confirmed available on the free hosted
endpoint (NVIDIA's 405B Llama model is currently listed as
"download/self-host only" on their catalog and returns a 404 through the
hosted API, so it's not usable here). You can override the model by setting
an `NVIDIA_MODEL` variable to any model ID from the catalog at
build.nvidia.com/models — just check the model's catalog page says it
supports live API calls, not just download, before switching to it. The
free tier allows roughly 40 requests/minute.

Note: chat memory is in-memory only, scoped per channel, and resets when
the bot restarts — it doesn't persist to the vouch data file.

## Scheduled event pings

The bot automatically pings a role in channel `1529142467658649640` at the
exact scheduled times for three recurring Deepwoken world events, based on
Libya (Africa/Tripoli, UTC+2) local time:

- **Carnival of Hearts**
- **Interluminary Parasol**
- **Battle Royale**
- **Doom of Caeranthil**

Each event pings a Discord role with the **exact same name** as the event
(e.g. a role literally called "Carnival of Hearts" must exist in the
server) — same pattern as the rank roles. If no matching role is found, it
still posts the ping with the event name in bold instead of a mention, and
logs a warning so you know to create the role.

- `?testeventping <event name>` — manually fires a ping right now to test
  the role/channel setup, without waiting for the actual scheduled time.
  Requires Manage Server permission.

To change the times, timezone, or channel, edit `EVENT_PING_SCHEDULE`,
`EVENT_PING_TZ`, and `EVENT_PING_CHANNEL_ID` near the top of `vouch_bot.py`.

## Tickets

`?ticketpanel` / `/ticketpanel` (Manage Server only) posts a panel with a **Host Request**
button in the current channel. Clicking it opens a private ticket channel
(visible only to the opener and anyone with Manage Server) and immediately
grants the opener the **Stage Perms** role. Staff closes the ticket with the
"Close Ticket (after host)" button in that channel, which removes Stage Perms
from the opener and deletes the channel a few seconds later.

Only the Host Request ticket type touches Stage Perms — any other ticket
type added to the panel later would not grant or remove it. If someone
already has an open Host Request ticket, clicking the button again just
points them back to it instead of opening a duplicate.

- `STAGE_PERMS_ROLE_NAME` (env var, default `Stage Perms`) — the exact role
  name to grant/revoke. Must already exist in the server, and the bot's role
  must sit above it.
- New ticket channels are created under the **Host Requests** category by
  default (looked up by name — create a category with that exact name in
  the server). Override the name with `TICKET_CATEGORY_NAME`, or pin an
  exact category by ID with `TICKET_CATEGORY_ID`. If neither resolves to a
  real category, the channel is created with no category.

## Persistent storage (important)

Railway wipes its normal filesystem on every redeploy. Attach a **Volume**
mounted at `/data` (service → ⋯ menu → Attach volume) so `vouches.json`
survives redeploys and restarts. The bot already reads/writes there by
default. After attaching the volume, run `?syncvouches` once to recover any
history from before it was added.
