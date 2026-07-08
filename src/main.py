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

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import cloudscraper
import requests
from dotenv import load_dotenv
from procyclingstats import Race, Stage
from procyclingstats.errors import ExpectedParsingError

# Load .env file for local development (ignored if not present)
load_dotenv()

PCS_BASE_URL = "https://www.procyclingstats.com/"

# Single cloudscraper session for local development
_pcs_scraper = cloudscraper.create_scraper(
    browser={"browser": "chrome", "platform": "windows", "desktop": True},
)


def _fetch_pcs_html(relative_url: str) -> str:
    """
    Fetch HTML from procyclingstats.com.

    Uses ScrapingBee proxy if SCRAPINGBEE_API_KEY is set (for CI/cloud environments
    where datacenter IPs are blocked by Cloudflare). Falls back to direct cloudscraper
    for local development.

    Args:
        relative_url: Relative URL path on procyclingstats.com.

    Returns:
        Raw HTML string.
    """
    url = PCS_BASE_URL + relative_url
    api_key = os.environ.get("SCRAPFLY_API_KEY")

    if api_key:
        # Use Scrapfly to bypass Cloudflare from CI/datacenter IPs
        # cache=false ensures we always get fresh stage data, not a cached page
        response = requests.get(
            "https://api.scrapfly.io/scrape",
            params={
                "key": api_key,
                "url": url,
                "render_js": "false",
                "asp": "true",   # Anti-Scraping Protection: uses residential proxies to bypass Cloudflare
                "cache": "false",
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        result = data.get("result", {})

        if not result.get("success", False):
            raise ConnectionError(
                f"Scrapfly failed for {url}: "
                f"status={result.get('status_code')} "
                f"reason={data.get('error', {}).get('message', 'unknown')}"
            )

        content = result.get("content", "")
        if "Just a moment" in content or "cf-browser-verification" in content:
            raise ConnectionError(f"Scrapfly returned a Cloudflare challenge page for {url}")

        return content
    else:
        # Local dev: use cloudscraper directly (home IP not blocked)
        response = _pcs_scraper.get(url, timeout=30)
        response.raise_for_status()
        return response.text


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def load_config() -> dict:
    """
    Load race configuration from config.json.

    Automatically migrates the old single-race format to the new multi-race
    format (a 'races' list) if needed.

    Returns:
        Dict with 'races' list and 'last_update_id'.
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Migrate old single-race flat format to new races-list format
    if "race_url" in config:
        config["races"] = [{
            "race_url": config.pop("race_url"),
            "race_name": config.pop("race_name"),
            "start_date": config.pop("start_date"),
            "end_date": config.pop("end_date"),
            "top_n": config.pop("top_n", 5),
        }]

    return config


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

    When triggered by the Cloudflare Worker webhook relay, reads the command
    directly from the WEBHOOK_COMMAND env var (getUpdates is unavailable in
    webhook mode). Falls back to getUpdates polling for manual/cron runs.

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
    # When triggered by the Cloudflare Worker, the command arrives via env vars
    webhook_command = os.environ.get("WEBHOOK_COMMAND", "").strip()
    webhook_chat_id = os.environ.get("WEBHOOK_CHAT_ID", "").strip()

    if webhook_command:
        print(f"Processing webhook command: {webhook_command[:30]}")
        if webhook_chat_id != chat_id:
            print("Webhook command from unauthorized chat. Ignoring.")
            return False
        return _dispatch_command(config, token, chat_id, webhook_command)

    # Fall back to getUpdates polling (cron / manual workflow_dispatch runs)
    offset = config.get("last_update_id", 0) + 1
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"offset": offset, "timeout": 5}

    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code == 409:
            # 409 Conflict: a webhook is active — getUpdates is disabled.
            # Commands arrive via WEBHOOK_COMMAND env var instead.
            print("Webhook mode active — skipping getUpdates polling.")
            return False
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

        config_changed = _dispatch_command(config, token, chat_id, text) or config_changed

    return config_changed


def _dispatch_command(config: dict, token: str, chat_id: str, text: str) -> bool:
    """Route a command text string to the appropriate handler.

    Args:
        config: Current configuration dict (modified in place).
        token: Bot API token.
        chat_id: Authorized chat ID to reply to.
        text: Raw command text (e.g. '/setrace\\nurl: ...').

    Returns:
        True if config was modified, False otherwise.
    """
    if text.startswith("/setrace"):
        return _handle_setrace(config, token, chat_id, text)
    elif text.startswith("/currentrace"):
        _handle_currentrace(config, token, chat_id)
    elif text.startswith("/help"):
        _handle_help(token, chat_id)
    return False


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

    # Build the new race entry
    new_race = {
        "race_url": params["url"],
        "race_name": params["name"],
        "start_date": params["start"],
        "end_date": params["end"],
        "top_n": int(params.get("top", 5)),
    }

    # Add to list, or update if the same URL already exists
    races = config.setdefault("races", [])
    for i, race in enumerate(races):
        if race["race_url"] == new_race["race_url"]:
            races[i] = new_race
            action = "updated"
            break
    else:
        races.append(new_race)
        action = "added"

    # Sort races by start date so the list is chronological
    races.sort(key=lambda r: r["start_date"])

    send_telegram_message(token, chat_id,
        f"✅ *Race {action}!*\n"
        f"🏁 {new_race['race_name']}\n"
        f"📅 {new_race['start_date']} → {new_race['end_date']}\n"
        f"🔗 `{new_race['race_url']}`\n"
        f"📊 Top {new_race['top_n']}")

    print(f"Race {action}: {new_race['race_name']}")
    return True


def _handle_currentrace(config: dict, token: str, chat_id: str) -> None:
    """
    Handle /currentrace command. Shows all configured races.

    Args:
        config: Current config dict.
        token: Bot API token.
        chat_id: Chat ID to reply to.
    """
    races = config.get("races", [])
    if not races:
        send_telegram_message(token, chat_id, "No races configured yet. Use /setrace to add one.")
        return

    today = date.today()
    lines = ["📋 *Configured races:*\n"]
    for race in races:
        start = date.fromisoformat(race["start_date"])
        end = date.fromisoformat(race["end_date"])
        if start <= today <= end:
            status = "🟢 active"
        elif today < start:
            status = "🔜 upcoming"
        else:
            status = "✅ finished"
        lines.append(
            f"{status} *{race['race_name']}*\n"
            f"  📅 {race['start_date']} → {race['end_date']}\n"
            f"  🔗 `{race['race_url']}`"
        )
    send_telegram_message(token, chat_id, "\n\n".join(lines))


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


def get_today_stage_url(config: dict) -> tuple[str, dict] | None:
    """
    Find today's active race and stage URL by checking all configured races.

    Args:
        config: Config dict containing a 'races' list.

    Returns:
        Tuple of (stage_url, race_config) if a stage is scheduled today,
        None otherwise.
    """
    today = date.today()
    races = config.get("races", [])

    for race in races:
        start = date.fromisoformat(race["start_date"])
        end = date.fromisoformat(race["end_date"])

        if today < start or today > end:
            continue

        # This race is active today — find today's stage
        html = _fetch_pcs_html(race["race_url"])
        pcs_race = Race(race["race_url"], html=html, update_html=False)
        stages = pcs_race.stages()
        print(f"Fetched {len(stages)} stages for {race['race_name']}")

        today_str = today.strftime("%m-%d")
        for stage in stages:
            if stage.get("date") == today_str:
                return stage.get("stage_url"), race

        print(f"No stage found for today ({today}) in {race['race_name']}. Likely a rest day.")
        return None

    print(f"Today ({today}) is not within any configured race dates.")
    return None


def fetch_results(stage_url: str, top_n: int) -> dict | None:
    """
    Fetch stage results and GC from Procyclingstats.

    Args:
        stage_url: Relative URL of the stage.
        top_n: Number of top results to include.

    Returns:
        Dict with 'stage_results', 'gc', and stage metadata, or None if unavailable.
    """
    html = _fetch_pcs_html(stage_url)
    stage = Stage(stage_url, html=html, update_html=False)

    try:
        stage_results = stage.results("rank", "rider_name", "team_name", "time")
    except ExpectedParsingError:
        # Results not posted yet (stage still in progress or not started)
        return None

    gc_results = stage.gc("rank", "rider_name", "team_name", "time")

    return {
        "departure": stage.departure(),
        "arrival": stage.arrival(),
        "distance": stage.distance(),
        "date": stage.date(),
        "stage_results": stage_results[:top_n],
        "gc": gc_results[:top_n],
    }


def _time_to_seconds(time_str: str) -> int:
    """
    Convert a time string (H:MM:SS, M:SS, or with decimals) to total seconds.

    Args:
        time_str: Time in "H:MM:SS" or "M:SS" format (may have decimals).

    Returns:
        Total seconds (rounded).
    """
    parts = time_str.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
    elif len(parts) == 2:
        return int(parts[0]) * 60 + int(float(parts[1]))
    return 0


def _format_gap(seconds: int) -> str:
    """
    Format a time gap in seconds to a readable string.

    Args:
        seconds: Gap in seconds.

    Returns:
        Formatted gap string (e.g., "+12s", "+1:23", "+1:02:30").
    """
    if seconds == 0:
        return "s.t."
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"+{h}:{m:02d}:{s:02d}"
    elif m > 0:
        return f"+{m}:{s:02d}"
    else:
        return f"+{s}s"


def _format_results_block(results: list, leader_time: str) -> str:
    """
    Format a results list showing gaps from the leader.

    Args:
        results: List of result dicts with rank, rider_name, team_name, time.
        leader_time: The leader's absolute time string.

    Returns:
        Formatted string block.
    """
    leader_secs = _time_to_seconds(leader_time)
    lines = []

    for r in results:
        rank = r["rank"]
        name = r["rider_name"]
        team = r["team_name"]
        rider_secs = _time_to_seconds(r["time"])
        gap = rider_secs - leader_secs

        if rank == 1:
            lines.append(f"  {rank}. {name} ({team})")
        else:
            gap_str = _format_gap(gap)
            lines.append(f"  {rank}. {name}  {gap_str}")

    return "\n".join(lines)


def format_message(config: dict, stage_url: str, data: dict) -> str:
    """
    Format results into a clean Telegram-friendly message.

    Args:
        config: Race configuration dict.
        stage_url: The stage URL (used to extract stage name).
        data: Dict with stage results and GC data.

    Returns:
        Formatted message string.
    """
    stage_name = stage_url.split("/")[-1].replace("-", " ").title()
    top_n = config["top_n"]

    stage_block = _format_results_block(
        data["stage_results"], data["stage_results"][0]["time"])
    gc_block = _format_results_block(
        data["gc"], data["gc"][0]["time"])

    msg = (
        f"🚴 *{config['race_name']} — {stage_name}*\n"
        f"📍 {data['departure']} → {data['arrival']} | {data['distance']} km\n"
        f"\n"
        f"🏁 *Stage Top {top_n}*\n"
        f"{stage_block}\n"
        f"\n"
        f"🟡 *GC Top {top_n}*\n"
        f"{gc_block}"
    )

    return msg


def main():
    """Main entry point: process commands, then fetch/send results if applicable."""
    parser = argparse.ArgumentParser(description="Cycling Results Bot")
    parser.add_argument(
        "--commands-only",
        action="store_true",
        help="Only process Telegram commands, skip results fetching.",
    )
    args = parser.parse_args()

    token, chat_id = get_telegram_credentials()
    config = load_config()

    # Step 1: Process any pending Telegram commands
    print("Checking for pending Telegram commands...")
    config_changed = process_telegram_commands(config, token, chat_id)

    # Always save (at minimum updates last_update_id)
    save_config(config)

    if args.commands_only:
        print("Commands-only mode. Skipping results.")
        return

    if config_changed:
        print("Config was updated. Will use new config for results.")

    # Step 2: Send today's stage results if applicable
    try:
        result = get_today_stage_url(config)
    except Exception as e:
        msg = f"⚠️ Bot error fetching stage: {e}"
        print(msg)
        send_telegram_message(token, chat_id, msg)
        return
    if not result:
        print("No stage today. Exiting.")
        return

    stage_url, active_race = result
    print(f"Race: {active_race['race_name']} — fetching: {stage_url}")
    data = fetch_results(stage_url, active_race["top_n"])
    if not data:
        print("Results not available yet. Stage may still be in progress.")
        return
    message = format_message(active_race, stage_url, data)
    print(message)
    send_telegram_message(token, chat_id, message)


if __name__ == "__main__":
    main()
