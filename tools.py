import os
from datetime import datetime

import markdown
import requests
from strands import tool


@tool
def get_rust_server_logs(hours: int = 24) -> str:
    """
    Fetch logs from the Rust game server via OpenSearch.

    Log types:
    - "Team" / "Global": Player chat messages (team chat and global chat)
    - Other logs: Internal server events (kills, connections, disconnections,
      base events, raids, world events, admin actions, etc.)

    Args:
        hours: Number of hours to look back (default: 24)

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

    query = {
        "query": {
            "range": {
                "@timestamp": {
                    "gte": f"now-{hours}h",
                    "lte": "now"
                }
            }
        },
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
    output_dir = os.getenv("REPORT_OUTPUT_DIR", "./reports")
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
