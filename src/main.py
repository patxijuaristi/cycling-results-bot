"""
Cycling Results Telegram Bot.

Fetches daily stage results and GC classification from Procyclingstats
and sends a formatted message via Telegram. Race configuration is managed
via Telegram commands and stored in config.json.

Supported commands (sent to the bot via Telegram):
    /setrace <url> <name> <start_date> <end_date> [top_n]
    /currentrace
    /help
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import requests
from procyclingstats import Race, Stage


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def load_config() -> dict:
    """
    Load race configuration from config.json.

    Returns:
        Dict with race_url, race_name, start_date, end_date, top_n, last_update_id.
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    """
    Save race configuration to config.json.

    Args:
        config: Configuration dict to persist.
    """
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
        f.write("\n")


def get_telegram_credentials() -> tuple[str, str]:
    """
    Get Telegram bot credentials from environment variables.

    Returns:
        Tuple of (bot_token, chat_id).
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.")
        sys.exit(1)

    return token, chat_id


def send_telegram_message(token: str, chat_id: str, message: str) -> None:
    """
    Send a message via Telegram Bot API.

    Args:
        token: Bot API token.
        chat_id: Target chat ID.
        message: Text to send (supports Markdown).
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    response = requests.post(url, json=payload, timeout=30)
    if response.status_code == 200:
        print("Message sent successfully.")
    else:
        print(f"Failed to send message: {response.status_code} - {response.text}")


def process_telegram_commands(config: dict, token: str, chat_id: str) -> bool:
    """
    Check for pending Telegram commands and process them.

    Supported commands:
        /setrace <url> <name> <start_date> <end_date> [top_n]
        /currentrace - Show current race config
        /help - Show available commands

    Args:
        config: Current configuration dict (modified in place).
        token: Bot API token.
        chat_id: Authorized chat ID (only commands from this chat are processed).

    Returns:
        True if config was modified, False otherwise.
    """
    # Fetch updates since last processed
    offset = config.get("last_update_id", 0) + 1
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"offset": offset, "timeout": 5}

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Failed to fetch Telegram updates: {e}")
        return False

    updates = response.json().get("result", [])
    if not updates:
        print("No pending commands.")
        return False

    config_changed = False

    for update in updates:
        config["last_update_id"] = update["update_id"]
        message = update.get("message", {})
        text = message.get("text", "")
        msg_chat_id = str(message.get("chat", {}).get("id", ""))

        # Only process messages from the authorized chat
        if msg_chat_id != chat_id:
            continue

        if text.startswith("/setrace"):
            config_changed = _handle_setrace(config, token, chat_id, text)
        elif text.startswith("/currentrace"):
            _handle_currentrace(config, token, chat_id)
        elif text.startswith("/help"):
            _handle_help(token, chat_id)

    return config_changed


def _handle_setrace(config: dict, token: str, chat_id: str, text: str) -> bool:
    """
    Handle /setrace command. Updates config with new race parameters.

    Format: /setrace <url> <name> <start_date> <end_date> [top_n]
    Example: /setrace race/vuelta-a-espana/2026 La Vuelta 2026 2026-08-14 2026-09-05 5

    Args:
        config: Config dict to update.
        token: Bot API token.
        chat_id: Chat ID to reply to.
        text: Full command text.

    Returns:
        True if config was updated successfully.
    """
    # Parse: /setrace <url> <start_date> <end_date> [top_n] <name...>
    # Better format: each param on separate lines or structured
    # Simple format: /setrace
    # url: race/vuelta-a-espana/2026
    # name: La Vuelta 2026
    # start: 2026-08-14
    # end: 2026-09-05

    lines = text.strip().split("\n")

    if len(lines) < 5:
        # Try single-line fallback: /setrace url start end [top_n]
        # with race name from procyclingstats
        send_telegram_message(token, chat_id,
            "⚠️ *Usage:*\n"
            "```\n"
            "/setrace\n"
            "url: race/vuelta-a-espana/2026\n"
            "name: La Vuelta 2026\n"
            "start: 2026-08-14\n"
            "end: 2026-09-05\n"
            "```\n"
            "Optional: add `top: 10` for top 10 results."
        )
        return False

    params = {}
    for line in lines[1:]:  # Skip the /setrace line
        if ":" in line:
            key, value = line.split(":", 1)
            params[key.strip().lower()] = value.strip()

    # Validate required fields
    required = ["url", "name", "start", "end"]
    missing = [k for k in required if k not in params]
    if missing:
        send_telegram_message(token, chat_id,
            f"❌ Missing fields: {', '.join(missing)}")
        return False

    # Validate dates
    try:
        date.fromisoformat(params["start"])
        date.fromisoformat(params["end"])
    except ValueError:
        send_telegram_message(token, chat_id,
            "❌ Invalid date format. Use YYYY-MM-DD.")
        return False

    # Update config
    config["race_url"] = params["url"]
    config["race_name"] = params["name"]
    config["start_date"] = params["start"]
    config["end_date"] = params["end"]
    config["top_n"] = int(params.get("top", config.get("top_n", 5)))

    send_telegram_message(token, chat_id,
        f"✅ *Race updated!*\n"
        f"🏁 {config['race_name']}\n"
        f"📅 {config['start_date']} → {config['end_date']}\n"
        f"🔗 `{config['race_url']}`\n"
        f"📊 Top {config['top_n']}")

    print(f"Config updated to: {config['race_name']}")
    return True


def _handle_currentrace(config: dict, token: str, chat_id: str) -> None:
    """
    Handle /currentrace command. Shows current configuration.

    Args:
        config: Current config dict.
        token: Bot API token.
        chat_id: Chat ID to reply to.
    """
    send_telegram_message(token, chat_id,
        f"📋 *Current configuration:*\n"
        f"🏁 {config['race_name']}\n"
        f"📅 {config['start_date']} → {config['end_date']}\n"
        f"🔗 `{config['race_url']}`\n"
        f"📊 Top {config['top_n']}")


def _handle_help(token: str, chat_id: str) -> None:
    """
    Handle /help command. Shows available commands.

    Args:
        token: Bot API token.
        chat_id: Chat ID to reply to.
    """
    send_telegram_message(token, chat_id,
        "🚴 *Cycling Results Bot - Commands:*\n\n"
        "*Set a new race:*\n"
        "```\n"
        "/setrace\n"
        "url: race/tour-de-france/2026\n"
        "name: Tour de France 2026\n"
        "start: 2026-07-04\n"
        "end: 2026-07-26\n"
        "top: 5\n"
        "```\n\n"
        "/currentrace - Show current config\n"
        "/help - Show this message")


def get_today_stage_url(config: dict) -> str | None:
    """
    Determine today's stage URL by matching the current date
    against the race stages calendar.

    Args:
        config: Race configuration dict.

    Returns:
        Stage URL string if a stage is scheduled today, None otherwise.
    """
    today = date.today()
    start = date.fromisoformat(config["start_date"])
    end = date.fromisoformat(config["end_date"])

    if today < start or today > end:
        print(f"Today ({today}) is outside {config['race_name']} dates ({start} to {end}).")
        return None

    # Fetch race overview to get stages with dates
    race = Race(config["race_url"])
    stages = race.stages()

    # Match today's date (format in stages is "MM-DD")
    today_str = today.strftime("%m-%d")
    for stage in stages:
        if stage.get("date") == today_str:
            return stage.get("stage_url")

    print(f"No stage found for today ({today}). Likely a rest day.")
    return None


def fetch_results(stage_url: str, top_n: int) -> dict:
    """
    Fetch stage results and GC from Procyclingstats.

    Args:
        stage_url: Relative URL of the stage.
        top_n: Number of top results to include.

    Returns:
        Dict with 'stage_results', 'gc', and stage metadata.
    """
    stage = Stage(stage_url)

    stage_results = stage.results("rank", "rider_name", "team_name", "time")
    gc_results = stage.gc("rank", "rider_name", "team_name", "time")

    return {
        "departure": stage.departure(),
        "arrival": stage.arrival(),
        "distance": stage.distance(),
        "date": stage.date(),
        "stage_results": stage_results[:top_n],
        "gc": gc_results[:top_n],
    }


def format_message(config: dict, stage_url: str, data: dict) -> str:
    """
    Format results into a Telegram-friendly message.

    Args:
        config: Race configuration dict.
        stage_url: The stage URL (used to extract stage name).
        data: Dict with stage results and GC data.

    Returns:
        Formatted message string.
    """
    stage_name = stage_url.split("/")[-1].replace("-", " ").title()
    top_n = config["top_n"]

    msg = f"🚴 *{config['race_name']} - {stage_name}*\n"
    msg += f"📍 {data['departure']} → {data['arrival']} ({data['distance']} km)\n"
    msg += f"📅 {data['date']}\n\n"

    msg += f"🏁 *Stage Results (Top {top_n}):*\n"
    for r in data["stage_results"]:
        time_str = f" - {r['time']}" if r.get("time") else ""
        msg += f"  {r['rank']}. {r['rider_name']} ({r['team_name']}){time_str}\n"

    msg += f"\n🟡 *General Classification (Top {top_n}):*\n"
    for r in data["gc"]:
        time_str = f" - {r['time']}" if r.get("time") else ""
        msg += f"  {r['rank']}. {r['rider_name']} ({r['team_name']}){time_str}\n"

    return msg


def main():
    """Main entry point: process commands, then fetch/send results if applicable."""
    token, chat_id = get_telegram_credentials()
    config = load_config()

    # Step 1: Process any pending Telegram commands
    print("Checking for pending Telegram commands...")
    config_changed = process_telegram_commands(config, token, chat_id)

    # Always save (at minimum updates last_update_id)
    save_config(config)

    if config_changed:
        print("Config was updated. Will use new config for results.")

    # Step 2: Send today's stage results if applicable
    print(f"Race: {config['race_name']}")
    stage_url = get_today_stage_url(config)
    if not stage_url:
        print("No stage today. Exiting.")
        return

    print(f"Fetching results for: {stage_url}")
    data = fetch_results(stage_url, config["top_n"])
    message = format_message(config, stage_url, data)
    print(message)
    send_telegram_message(token, chat_id, message)


if __name__ == "__main__":
    main()
