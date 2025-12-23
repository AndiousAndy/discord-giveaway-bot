# Discord Giveaway Bot with Invite Tracking

A simple Discord bot that runs giveaways where users get extra tickets based on how many people they invite!

## 🎯 How It Works

- **Everyone gets 1 base ticket** automatically
- **Invite friends to get +1 ticket per invite**
- **Maximum 5 extra tickets** from invites (total of 6 tickets max)
- More tickets = better chance to win!

## 🚀 Setup Instructions

### 1. Create a Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" and give it a name
3. Go to the "Bot" section and click "Add Bot"
4. **Enable these Privileged Gateway Intents:**
   - ✅ Server Members Intent
   - ✅ Message Content Intent
5. Click "Reset Token" and copy your bot token

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure the Bot

1. Copy `.env.example` to `.env`:
   ```bash
   copy .env.example .env
   ```

2. Edit `.env` and add your bot token:
   ```
   DISCORD_BOT_TOKEN=your_actual_token_here
   ```

### 4. Invite the Bot to Your Server

1. Go to OAuth2 > URL Generator in Discord Developer Portal
2. Select scopes:
   - ✅ `bot`
3. Select bot permissions:
   - ✅ Send Messages
   - ✅ Embed Links
   - ✅ Read Message History
   - ✅ Manage Roles (optional, for future features)
4. Copy the generated URL and open it in your browser
5. Select your server and authorize the bot

### 5. Run the Bot

```bash
python bot.py
```

You should see:
```
[Bot Name] has connected to Discord!
Loaded X invites for [Server Name]
Bot is ready!
```

## 📋 Commands

### For Everyone

| Command | Description |
|---------|-------------|
| `!tickets` | Check how many tickets you have |
| `!tickets @user` | Check how many tickets another user has |
| `!leaderboard` | View top 10 ticket holders |
| `!gstatus` | Check current giveaway status |
| `!help` | Show all commands |

### For Admins Only

| Command | Description |
|---------|-------------|
| `!giveaway <prize>` | Start a new giveaway |
| `!endgiveaway` | End the giveaway and pick a random winner |

## 🎮 Example Usage

### Starting a Giveaway

```
!giveaway Discord Nitro for 1 month
```

The bot will announce the giveaway and explain how to enter.

### Checking Tickets

```
!tickets
```

Shows:
- Total tickets
- Base ticket (1)
- Number of invites
- Extra tickets earned (max 5)

### Ending a Giveaway

```
!endgiveaway
```

The bot will:
1. Collect all tickets from all members
2. Randomly pick a winner (weighted by ticket count)
3. Announce the winner with their ticket count

## 🔧 Configuration

You can modify these settings in `bot.py`:

```python
MAX_EXTRA_TICKETS = 5  # Maximum extra tickets from invites
```

Change the prefix (default is `!`):
```python
bot = commands.Bot(command_prefix='!', intents=intents)
```

## 📊 Data Storage

The bot stores data in two JSON files:
- `invite_data.json` - Tracks invite counts per user
- `giveaway_data.json` - Stores giveaway information

These files are created automatically and persist between bot restarts.

## ⚠️ Important Notes

1. **The bot must be online** when members join to track invites
2. **Invites are tracked from when the bot starts** - previous invites won't count
3. Everyone gets 1 base ticket, even with 0 invites
4. Only one giveaway can be active at a time per server
5. Bot accounts are excluded from giveaways

## 🎫 Ticket System Example

| Invites | Base Ticket | Extra Tickets | Total Tickets |
|---------|-------------|---------------|---------------|
| 0 | 1 | 0 | **1** |
| 1 | 1 | 1 | **2** |
| 3 | 1 | 3 | **4** |
| 5 | 1 | 5 | **6** |
| 10 | 1 | 5 (capped) | **6** |

## 🐛 Troubleshooting

**Bot doesn't respond to commands:**
- Make sure Message Content Intent is enabled
- Check that the bot has permission to send messages in the channel

**Invites not tracking:**
- Ensure Server Members Intent is enabled
- The bot must be online when members join

**"Missing Permissions" error:**
- Make sure the bot has the required permissions in your server

## 📝 License

Free to use and modify for your Discord server!

---

Made with ❤️ for Discord giveaways
