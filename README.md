# 🚴 Cycling Results Bot

Telegram bot that sends daily stage race results. Configurable for any multi-stage race on Procyclingstats (Tour de France, La Vuelta, Giro d'Italia, etc.).

**Switch races directly from Telegram** — no code changes, no GitHub UI, just send a command.

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/setrace` | Configure a new race (see format below) |
| `/currentrace` | Show current race configuration |
| `/help` | Show available commands |

### Setting a Race
Send this multi-line message to the bot:
```
/setrace
url: race/tour-de-france/2026
name: Tour de France 2026
start: 2026-07-04
end: 2026-07-26
top: 5
```

Examples for other races:
```
/setrace
url: race/vuelta-a-espana/2026
name: La Vuelta 2026
start: 2026-08-14
end: 2026-09-05
```

Find the URL at [procyclingstats.com](https://www.procyclingstats.com/) — it's the path after the domain.

## Setup

### 1. Create a Telegram Bot
1. Talk to [@BotFather](https://t.me/BotFather) on Telegram
2. Create a new bot with `/newbot` and copy the token

### 2. Get Your Chat ID
1. Open a conversation with your new bot in Telegram and send any message (e.g., "hello")
2. Open this URL in your browser (replace `<TOKEN>` with your bot token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Look for `"chat":{"id":123456789,...}` in the response — that number is your chat ID

### 3. Configure GitHub Secrets
Go to `Settings > Secrets and variables > Actions > Secrets`:
| Secret | Description |
|--------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your chat ID (see step above) |
| `SCRAPFLY_API_KEY` | API key from [scrapfly.io](https://scrapfly.io) — free plan includes 1000 credits with no expiry date (credits don't reset monthly, but 1000 is enough for ~10 Grand Tours at ~2 requests/stage day) |

### 4. Push the code
The workflow runs daily at 6pm CEST. It will:
1. Check for any pending `/setrace` commands from Telegram
2. Update config if needed (auto-committed to the repo)
3. Send results if today is a race day

## Security & Multi-User

This bot is safe to publish as an open-source repository:

- **Only your chat ID can control the bot.** Commands from any other Telegram user are silently ignored. Authorization is based on the `TELEGRAM_CHAT_ID` secret — only messages from that chat are processed.
- **Others can fork & run their own instance.** Each person sets their own `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` secrets, creating a fully independent deployment.
- **Nobody else can change your race config.** Even if someone discovers your bot and sends it `/setrace`, it will be ignored because their chat ID doesn't match.

## How It Works
1. GitHub Actions triggers daily at 16:00 UTC (6pm CEST)
2. Checks Telegram for pending commands — processes config changes
3. If today is within race dates, fetches stage calendar from Procyclingstats
4. If a stage matches today, sends top N results + GC to Telegram
5. Commits any config changes back to the repo

## Local Testing
```bash
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"
pip install -r requirements.txt
python src/main.py
```

## Manual Trigger
Run the workflow anytime from the GitHub Actions tab using `workflow_dispatch` (useful for testing or processing commands immediately).
