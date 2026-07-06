---
applyTo: '**'
---
# Cycling Results Bot - Copilot Instructions

## Project Overview
This project is a Telegram bot that sends daily stage race results.
It is configurable for any multi-stage cycling race (Tour de France, La Vuelta, Giro d'Italia, etc.).
It runs via GitHub Actions every day at 6pm CEST. Race configuration is managed
via Telegram commands — no code changes or GitHub UI needed to switch races.

## Tech Stack
- **Language**: Python 3.12
- **Data source**: procyclingstats.com via the `procyclingstats` library
- **Messaging**: Telegram Bot API via `requests`
- **Scheduler**: GitHub Actions (cron)
- **Configuration**: `config.json` (updated via Telegram commands, committed by workflow)

## Project Structure
```
config.json              # Race config (managed via Telegram /setrace command)
src/main.py              # Main script: process commands, fetch results, send message
requirements.txt         # Python dependencies
.github/workflows/       # GitHub Actions workflow for daily execution
```

## Key Conventions
- Follow PEP 8 style guidelines.
- All functions must have docstrings with purpose, args, and return description.
- Sensitive configuration (tokens, chat IDs) must use GitHub Secrets, never hardcoded.
- Race-specific configuration is stored in `config.json` and managed via Telegram.
- Use type hints for function signatures.
- Keep the script simple and single-purpose — no unnecessary abstractions.
- **Never run `git commit` or `git push` unless explicitly asked by the user.**

## Telegram Commands
- `/setrace` - Set a new race (multi-line with url, name, start, end, top)
- `/currentrace` - Show current race configuration
- `/help` - Show available commands

## Data Flow
1. Workflow triggers daily at 6pm CEST.
2. Script checks for pending Telegram commands (processes /setrace, /currentrace, /help).
3. If config changed, workflow commits updated `config.json`.
4. Script checks if today falls within race dates.
5. Determines today's stage from Procyclingstats calendar.
6. Fetches stage results (top N) and GC classification (top N).
7. Sends formatted message via Telegram.

## Environment Variables (GitHub Secrets)
- `TELEGRAM_BOT_TOKEN`: Bot token from @BotFather
- `TELEGRAM_CHAT_ID`: Target chat/user ID for messages (also used for auth)
- `SCRAPINGBEE_API_KEY`: ScrapingBee API key to bypass Cloudflare from GitHub Actions IPs (free tier sufficient)

## Dependencies
- `procyclingstats` — Web scraper for procyclingstats.com (MIT license)
- `requests` — HTTP client for Telegram API (Apache 2.0 license)

## Testing
- Manual trigger via `workflow_dispatch` in GitHub Actions.
- For local testing, set env vars and run: `python src/main.py`
