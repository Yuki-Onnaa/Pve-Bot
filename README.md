# Vouch Counter Discord Bot

Counts vouches by watching for messages like:

    vouch @username Elder
    vouch @username Hellmode
    vouch @username Diluvian W (25)

Each vouch is worth points based on event type:

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

Matching is case-insensitive and flexible with spacing (e.g. "hell mode",
"hellmode", "Hell Mode" all work; "diluvian w 25" and "diluvian w (25)" both work).

## Setup

1. Create a bot at https://discord.com/developers/applications
   - Go to "Bot" tab, click "Add Bot"
   - Under "Privileged Gateway Intents", turn ON **Message Content Intent**
   - Copy the bot token (keep it secret!)
2. Invite the bot to your server using the OAuth2 URL generator
   (scope: `bot`; permissions: Send Messages, Read Message History, View Channels, Embed Links)
3. Install dependencies:
       pip install -r requirements.txt
4. Set your token as an environment variable (don't paste it into the code):
       export DISCORD_TOKEN="your_token_here"
5. Run it:
       python vouch_bot.py

## Commands

- `vouch @user <event>` — records a vouch (typed as a normal message in the vouch channel).
  The bot reacts instead of replying with a message:
  - ✅ = recorded successfully
  - ❌ = event type not recognized
  - 🚫 = tried to vouch for yourself
- `?vouches @user` — shows someone's point total and breakdown by event type
- `?leaderboard [n]` — shows the top n vouched users by points (default 10)
- `?addvouch @user <event> [count]` (alias: `?backfill`) — manually records old/historical
  vouches that weren't originally logged by the bot. Requires Manage Server permission.
  Example: `?addvouch @Nico Hellmode 3` adds 3 Hellmode vouches at once.

## Data storage

Vouch data is saved to `vouches.json` in the same folder, so it persists
across bot restarts. Back this file up if you move hosts.

## Restricting to one channel

The bot only reads vouch messages from the channel ID set in `VOUCH_CHANNEL_ID`
near the top of `vouch_bot.py`. Set it to `None` to watch every channel instead.
