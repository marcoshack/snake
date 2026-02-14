import os
import unicodedata
from datetime import datetime

import markdown
import requests
from strands import tool


@tool
def get_rust_server_logs(hours: int = 24, include: list[str] = None, exclude: list[str] = None) -> str:
    """
    Fetch logs from the Rust game server via OpenSearch.

    Log types:
    - "Team" / "Global": Player chat messages (team chat and global chat)
    - Other logs: Internal server events (kills, connections, disconnections,
      base events, raids, world events, admin actions, etc.)

    Args:
        hours: Number of hours to look back (default: 24)
        include: Optional list of terms to filter by. Only logs containing at
            least one of these terms will be returned. Example: ["[Global]", "[Better Say]"]
        exclude: Optional list of terms to exclude. Logs containing any of
            these terms will be filtered out. Example: ["[Team]"]

    Returns:
        Server logs with timestamps, useful for admin oversight
    """
    opensearch_host = os.environ.get("OPENSEARCH_HOST")
    opensearch_port = os.environ.get("OPENSEARCH_PORT", "9200")
    opensearch_user = os.environ.get("OPENSEARCH_USER")
    opensearch_password = os.environ.get("OPENSEARCH_PASSWORD")
    opensearch_index = os.environ.get("OPENSEARCH_INDEX")
    opensearch_result_size = int(os.environ.get("OPENSEARCH_RESULT_SIZE", "10000"))

    if not opensearch_host or not opensearch_user or not opensearch_password or not opensearch_index:
        return "Error: OPENSEARCH_HOST, OPENSEARCH_USER, OPENSEARCH_PASSWORD, and OPENSEARCH_INDEX environment variables must be set"

    url = f"http://{opensearch_host}:{opensearch_port}/{opensearch_index}/_search"
    headers = {"Content-Type": "application/json"}
    auth = (opensearch_user, opensearch_password)

    # Build the bool query with time range as a must clause
    must_clauses = [
        {"range": {"@timestamp": {"gte": f"now-{hours}h", "lte": "now"}}}
    ]

    # Include filter: log must contain at least one of the terms
    should_clauses = []
    if include:
        for term in include:
            should_clauses.append({"match_phrase": {"log": term}})

    # Exclude filter: log must not contain any of the terms
    must_not_clauses = []
    if exclude:
        for term in exclude:
            must_not_clauses.append({"match_phrase": {"log": term}})

    bool_query = {"must": must_clauses}
    if should_clauses:
        bool_query["should"] = should_clauses
        bool_query["minimum_should_match"] = 1
    if must_not_clauses:
        bool_query["must_not"] = must_not_clauses

    query = {
        "query": {"bool": bool_query},
        "sort": [{"@timestamp": {"order": "desc"}}],
        "size": opensearch_result_size
    }

    response = requests.get(url, headers=headers, auth=auth, json=query)
    response.raise_for_status()

    data = response.json()
    hits = data.get("hits", {}).get("hits", [])

    if not hits:
        return "No logs found in the specified time range."

    messages = []
    for hit in hits:
        source = hit.get("_source", {})
        timestamp = source.get("@timestamp", "unknown")
        log = source.get("log", "")
        messages.append(f"[{timestamp}] {log}")

    return "\n".join(messages)


@tool
def post_discord_admin_alert(message: str) -> str:
    """
    Post an alert to the Rust server admin Discord channel.

    Use this to notify admins about issues requiring attention:
    - Cheating attempts or suspicious behavior
    - Technical problems (server errors, crashes)
    - Rule violations
    - Other urgent matters

    Args:
        message: Short alert message (keep it concise and actionable)

    Returns:
        Confirmation of message posted or error
    """
    webhook_url = os.environ.get("DISCORD_RUST_ADMIN_WEBHOOK")
    if not webhook_url:
        return "Error: DISCORD_RUST_ADMIN_WEBHOOK environment variable not set"

    payload = {"content": message}
    response = requests.post(webhook_url, json=payload)

    if response.status_code == 204:
        return "Alert posted to Discord successfully"
    else:
        return f"Failed to post to Discord: {response.status_code} - {response.text}"


@tool
def save_report_html(report_markdown: str, filename: str = None) -> str:
    """
    Save the analysis report as a rendered HTML file.

    Args:
        report_markdown: The report content in markdown format
        filename: Optional filename (without extension). Defaults to timestamp-based name.

    Returns:
        Path to the saved HTML file or error message
    """
    output_dir = os.getenv("SNAKE_REPORT_DIR", os.getenv("REPORT_OUTPUT_DIR", "./reports"))
    os.makedirs(output_dir, exist_ok=True)

    if not filename:
        filename = f"rust-server-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    html_content = markdown.markdown(
        report_markdown,
        extensions=["tables", "fenced_code", "nl2br"]
    )

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rust Server Report - {datetime.now().strftime('%Y-%m-%d %H:%M')}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #1a1a1a;
            color: #e0e0e0;
        }}
        h1, h2, h3 {{ color: #ff6b35; }}
        code {{
            background: #2d2d2d;
            padding: 2px 6px;
            border-radius: 3px;
        }}
        pre {{
            background: #2d2d2d;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 15px 0;
        }}
        th, td {{
            border: 1px solid #444;
            padding: 10px;
            text-align: left;
        }}
        th {{ background: #2d2d2d; }}
        .timestamp {{ color: #888; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
    {html_content}
</body>
</html>"""

    filepath = os.path.join(output_dir, f"{filename}.html")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_html)

    return f"Report saved to: {filepath}"


MAX_CHAT_MESSAGE_LENGTH = 128


def _transliterate_to_ascii(text: str) -> str:
    """Transliterate non-ASCII characters to their closest ASCII equivalents.

    The Rust RCON 'say' command does not support non-ASCII characters — they
    render as '??' in game chat. This converts accented characters to their
    base forms (e.g. é→e, ã→a, ç→c) and drops any remaining non-ASCII
    characters that have no sensible ASCII mapping.
    """
    # Decompose unicode characters (e.g. é → e + combining accent)
    # then drop the combining marks, keeping only the base characters
    nfkd = unicodedata.normalize("NFKD", text)
    return nfkd.encode("ascii", "ignore").decode("ascii")


@tool
def send_global_chat_message(message: str) -> str:
    """
    Send a message to the Rust server's Global chat channel.

    The message appears in-game as a server broadcast visible to all players.
    Uses the RCON "say" command behind the scenes.

    Limitations (enforced by the Rust server):
    - Maximum 128 characters per message
    - Single-line only (no newlines)
    - ASCII only (non-ASCII characters like accents are automatically
      transliterated to their closest ASCII equivalents, e.g. é→e, ã→a)

    Args:
        message: The text to broadcast in Global chat (max 128 chars, no newlines).
            Use only ASCII characters — accented characters will be transliterated
            automatically but may lose meaning.

    Returns:
        Confirmation of message sent or error
    """
    endpoint = os.environ.get("SNAKE_CHAT_API_ENDPOINT")
    if not endpoint:
        return "Error: SNAKE_CHAT_API_ENDPOINT environment variable not set"

    if not message or not message.strip():
        return "Error: Message cannot be empty"

    if "\n" in message or "\r" in message:
        return "Error: Message cannot contain newlines (RCON say command is single-line only)"

    # Transliterate non-ASCII characters to avoid '??' rendering in game chat
    message = _transliterate_to_ascii(message)

    if len(message) > MAX_CHAT_MESSAGE_LENGTH:
        return f"Error: Message exceeds {MAX_CHAT_MESSAGE_LENGTH} character limit ({len(message)} chars). Shorten the message and try again."

    response = requests.post(endpoint, json={"message": message})

    if response.ok:
        return "Message sent to Global chat successfully"
    else:
        return f"Failed to send chat message: {response.status_code} - {response.text}"


TOOL_REGISTRY = {
    "get_rust_server_logs": get_rust_server_logs,
    "post_discord_admin_alert": post_discord_admin_alert,
    "save_report_html": save_report_html,
    "send_global_chat_message": send_global_chat_message,
}
