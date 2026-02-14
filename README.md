# Snake

AI-powered monitoring system for Rust game servers. Snake runs multiple autonomous agents on independent schedules, each analyzing server logs from OpenSearch and posting alerts to Discord.

## Architecture

Snake uses the [Strands Agents SDK](https://github.com/strands-agents/sdk-python) to run Claude-based agents. Each agent is defined as a markdown file in the `agents/` directory with YAML frontmatter for configuration and a prompt template as the body. Agent definitions are re-read from disk on every run cycle, so you can update prompts without restarting the process.

```
snake/
  main.py              # Scheduler and agent runner
  tools.py             # Tool definitions (OpenSearch, Discord, reports)
  agents/              # Agent definitions (markdown + YAML frontmatter)
    operational-report.md
    admin-chatbot.md
```

## Agents

### operational-report

Periodically fetches all server logs and produces a comprehensive analysis covering cheating detection, technical issues, and notable incidents. Posts a summary to Discord and saves a full HTML report.

### admin-chatbot

Monitors global chat and bot messages (e.g., Better Say) to identify player reports, technical complaints, and community sentiment. Posts categorized summaries to Discord with priority levels.

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key | (required) |
| `OPENSEARCH_HOST` | OpenSearch hostname | (required) |
| `OPENSEARCH_PORT` | OpenSearch port | `9200` |
| `OPENSEARCH_USER` | OpenSearch username | (required) |
| `OPENSEARCH_PASSWORD` | OpenSearch password | (required) |
| `OPENSEARCH_INDEX` | Log index name | (required) |
| `OPENSEARCH_RESULT_SIZE` | Max results per query | `10000` |
| `DISCORD_RUST_ADMIN_WEBHOOK` | Discord webhook URL for alerts | (required) |
| `REPORT_OUTPUT_DIR` | Directory for HTML reports | `./reports` |
| `LOG_DIR` | Directory for agent execution logs | `./logs` |
| `SNAKE_AGENTS` | Agents and their frequencies | `operational-report:24h` |
| `SNAKE_AGENTS_DIR` | Path to agent definitions | `./agents` |
| `SNAKE_WEBHOOK_PORT` | Port for the webhook HTTP server | `8000` |

### SNAKE_AGENTS format

Comma-separated `name:frequency` pairs. The frequency also determines the log query period (with a 10% buffer).

```bash
# Run operational-report every hour, admin-chatbot every 10 minutes
SNAKE_AGENTS=operational-report:1h,admin-chatbot:10m
```

Supported frequency units: `m` (minutes), `h` (hours), `d` (days), `w` (weeks).

Agents can also use `webhook` as their frequency to be triggered on-demand via HTTP instead of running on a schedule:

```bash
# operational-report runs every hour, admin-chatbot is triggered via webhook
SNAKE_AGENTS=operational-report:1h,admin-chatbot:webhook
```

Webhook-triggered agents use a default query period of 5 minutes.

### Webhooks

Snake starts an HTTP server (default port `8000`, configurable via `SNAKE_WEBHOOK_PORT`) that accepts POST requests to trigger agents on demand. Any agent listed in `SNAKE_AGENTS` can be triggered via webhook, regardless of whether it also runs on a schedule.

```bash
# Trigger the admin-chatbot agent
curl -X POST http://localhost:8000/agents/admin-chatbot
```

The server responds with `202 Accepted` and queues the agent for immediate execution. If the agent name is not found, it returns `404`.

When running with Docker Compose, the webhook port is exposed to the host automatically.

## Running locally

```bash
uv sync
uv run python main.py
```

## Running with Docker Compose

```bash
docker compose up -d
```

Agent definitions are mounted as a volume, so edits to `agents/*.md` take effect on the next run cycle without rebuilding the container.

## Creating a new agent

1. Create a markdown file in `agents/`, e.g. `agents/my-agent.md`:

```markdown
---
tools:
  - get_rust_server_logs
  - post_discord_admin_alert
  - save_report_html
model: claude-sonnet-4-20250514
max_tokens: 4096
---

Your prompt template here. Use {period_hours} and {period_minutes}
as template variables for the log query period.
```

2. Add it to `SNAKE_AGENTS`:

```bash
SNAKE_AGENTS=operational-report:1h,my-agent:30m
```

### Available tools

| Tool | Description |
|---|---|
| `get_rust_server_logs` | Fetch logs from OpenSearch with optional `include`/`exclude` term filters |
| `post_discord_admin_alert` | Post a message to the admin Discord channel |
| `save_report_html` | Save a markdown report as a rendered HTML file |
