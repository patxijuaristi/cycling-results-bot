/**
 * Cloudflare Worker: Telegram → GitHub Actions relay
 *
 * Receives Telegram webhook POST requests and triggers the
 * "Process Telegram Commands" GitHub Actions workflow via
 * the repository_dispatch API.
 *
 * Required Worker secrets (set via Wrangler or the Cloudflare dashboard):
 *   GITHUB_TOKEN  — GitHub Personal Access Token with `repo` scope
 *   TELEGRAM_BOT_TOKEN — Used to verify the webhook URL is legitimate
 *
 * Required Worker variable (set in wrangler.toml or dashboard):
 *   GITHUB_REPO — e.g. "patxijuaristi/cycling-results-bot"
 */

export default {
  async fetch(request, env) {
    // Only accept POST requests
    if (request.method !== "POST") {
      return new Response("OK", { status: 200 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    const text = body?.message?.text ?? body?.channel_post?.text ?? "";

    // Only trigger a workflow run if the message is a bot command
    if (!text.startsWith("/")) {
      return new Response("OK", { status: 200 });
    }

    // Trigger GitHub Actions via repository_dispatch
    const response = await fetch(
      `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github.v3+json",
          "Content-Type": "application/json",
          "User-Agent": "cycling-results-bot-worker",
        },
        body: JSON.stringify({
          event_type: "telegram-command",
          client_payload: {
            command: text,
            chat_id: String(body?.message?.chat?.id ?? ""),
          },
        }),
      }
    );

    if (!response.ok) {
      const errorBody = await response.text();
      console.error(`GitHub API error: ${response.status} — ${errorBody}`);
      console.error(`Token present: ${!!env.GITHUB_TOKEN}, repo: ${env.GITHUB_REPO}`);
    }

    return new Response("OK", { status: 200 });
  },
};
