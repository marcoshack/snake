import json
import logging
import logging.handlers
import os
import queue
import re
import signal
import sys
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import yaml
from dotenv import load_dotenv
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.anthropic import AnthropicModel
from strands.session import FileSessionManager
from tools import TOOL_REGISTRY

load_dotenv()

# Flag for graceful shutdown
shutdown_requested = False

DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 4096

# Main application logger (stdout)
logger = logging.getLogger("snake")


def setup_logging() -> None:
    """Configure the main application logger to write to stdout."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def setup_agent_logger(name: str, log_dir: Path) -> logging.Logger:
    """Create a per-agent logger with daily file rotation.

    Each agent gets its own logger writing to log_dir/<name>.log,
    rotating at midnight and keeping 30 days of history.
    """
    agent_logger = logging.getLogger(f"snake.agent.{name}")
    agent_logger.setLevel(logging.INFO)
    agent_logger.propagate = False

    handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / f"{name}.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"))
    agent_logger.addHandler(handler)
    return agent_logger


class LoggerWriter:
    """File-like object that redirects writes to a logger."""

    def __init__(self, log: logging.Logger):
        self._logger = log
        self._buf = ""

    def write(self, msg: str) -> int:
        if not msg:
            return 0
        self._buf += msg
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line:
                self._logger.info("%s", line)
        return len(msg)

    def flush(self) -> None:
        if self._buf:
            self._logger.info("%s", self._buf)
            self._buf = ""


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    logger.info("Received signal %s, shutting down gracefully...", signum)
    shutdown_requested = True


def parse_duration(duration_str: str) -> int:
    """
    Parse a duration string into seconds.

    Supported formats:
    - "30m" or "30M" -> 30 minutes
    - "24h" or "24H" -> 24 hours
    - "1d" or "1D" -> 1 day
    - "1w" or "1W" -> 1 week

    Returns the duration in seconds.
    """
    duration_str = duration_str.strip().lower()

    match = re.match(r'^(\d+)\s*([mhdw])$', duration_str)
    if not match:
        raise ValueError(
            f"Invalid duration format: '{duration_str}'. "
            "Expected format like '30m', '24h', '1d', or '1w'."
        )

    value = int(match.group(1))
    unit = match.group(2)

    multipliers = {
        'm': 60,           # minutes
        'h': 3600,         # hours
        'd': 86400,        # days
        'w': 604800,       # weeks
    }

    return value * multipliers[unit]


def parse_agents_config(agents_str: str) -> list[dict]:
    """
    Parse the SNAKE_AGENTS env var into a list of agent configs.

    Format: "name1:frequency1,name2:frequency2"
    Example: "operational-report:1h,admin-chatbot:webhook"

    Frequency can be a duration (e.g., "1h", "30m") for scheduled agents,
    or "webhook" for agents triggered by HTTP webhook calls.

    Returns a list of dicts with keys: name, frequency, interval_seconds, period_minutes
    """
    agents = []
    for entry in agents_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(
                f"Invalid agent entry '{entry}'. "
                "Expected format 'name:frequency' (e.g., 'operational-report:1h' or 'admin-chatbot:webhook')."
            )
        name, frequency = entry.split(":", 1)
        name = name.strip()
        frequency = frequency.strip()

        if frequency == "webhook":
            agents.append({
                "name": name,
                "frequency": "webhook",
                "interval_seconds": None,
                "period_minutes": 5,
            })
        else:
            interval_seconds = parse_duration(frequency)
            period_minutes = int((interval_seconds / 60) * 1.1)
            agents.append({
                "name": name,
                "frequency": frequency,
                "interval_seconds": interval_seconds,
                "period_minutes": period_minutes,
            })
    return agents


def load_agent_definition(name: str, agents_dir: Path) -> dict:
    """
    Load an agent definition from a markdown file.

    The file uses YAML frontmatter for configuration and the body as the
    prompt template. Template variables {period_hours} and {period_minutes}
    are substituted at runtime.

    Returns a dict with keys: tools, model, max_tokens, prompt_template
    """
    filepath = agents_dir / f"{name}.md"
    if not filepath.exists():
        raise FileNotFoundError(f"Agent definition not found: {filepath}")

    content = filepath.read_text()

    # Parse YAML frontmatter (between --- delimiters)
    if not content.startswith("---"):
        raise ValueError(f"Agent definition {filepath} must start with YAML frontmatter (---)")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Agent definition {filepath} has invalid frontmatter format")

    frontmatter = yaml.safe_load(parts[1])
    prompt_template = parts[2].strip()

    tool_names = frontmatter.get("tools", [])
    tools = []
    for tool_name in tool_names:
        if tool_name not in TOOL_REGISTRY:
            raise ValueError(f"Unknown tool '{tool_name}' in agent '{name}'. Available: {list(TOOL_REGISTRY.keys())}")
        tools.append(TOOL_REGISTRY[tool_name])

    return {
        "tools": tools,
        "model": frontmatter.get("model", DEFAULT_MODEL),
        "max_tokens": frontmatter.get("max_tokens", DEFAULT_MAX_TOKENS),
        "prompt_template": prompt_template,
    }


def create_agent(name: str, agents_dir: Path, period_minutes: int, sessions_dir: Path) -> tuple[Agent, dict] | None:
    """Create a persistent agent instance from its definition file.

    Uses FileSessionManager to persist conversation history to disk so it
    survives process/container restarts.

    Returns a tuple of (Agent, definition_dict) or None if loading fails.
    """
    try:
        definition = load_agent_definition(name, agents_dir)
    except (FileNotFoundError, ValueError) as e:
        logger.error("Failed to load agent '%s': %s", name, e)
        return None

    period_hours = max(1, int((period_minutes + 59) / 60))
    system_prompt = definition["prompt_template"].format(
        period_hours=period_hours,
        period_minutes=period_minutes,
    )

    model = AnthropicModel(model_id=definition["model"], max_tokens=definition["max_tokens"])
    session_manager = FileSessionManager(
        session_id=f"snake-{name}",
        storage_dir=str(sessions_dir),
    )
    window_size = int(os.environ.get("SNAKE_CONTEXT_WINDOW_SIZE", "20"))
    conversation_manager = SlidingWindowConversationManager(window_size=window_size)
    agent = Agent(
        model=model,
        tools=definition["tools"],
        system_prompt=system_prompt,
        session_manager=session_manager,
        conversation_manager=conversation_manager,
        agent_id=name,
    )

    logger.info("Created persistent agent '%s' (session: %s)", name, sessions_dir)
    return agent, definition


def refresh_agent_system_prompt(agent: Agent, name: str, agents_dir: Path, period_minutes: int) -> None:
    """Reload the agent definition from disk and update the system prompt.

    This allows hot-reloading prompt changes without losing conversation history.
    """
    try:
        definition = load_agent_definition(name, agents_dir)
    except (FileNotFoundError, ValueError) as e:
        logger.error("Failed to reload agent '%s': %s", name, e)
        return

    period_hours = max(1, int((period_minutes + 59) / 60))
    agent.system_prompt = definition["prompt_template"].format(
        period_hours=period_hours,
        period_minutes=period_minutes,
    )


def run_agent(agent: Agent, name: str, agents_dir: Path, period_minutes: int,
              log_dir: Path, agent_loggers: dict[str, logging.Logger]) -> None:
    """Run a single analysis cycle on a persistent agent instance."""
    logger.info("Running agent '%s'...", name)

    # Reload system prompt from disk to pick up any changes
    refresh_agent_system_prompt(agent, name, agents_dir, period_minutes)

    agent_log = agent_loggers[name]
    agent_log.info("=" * 80)
    agent_log.info("Run started")
    agent_log.info("=" * 80)

    try:
        writer = LoggerWriter(agent_log)
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = writer
        sys.stderr = writer
        try:
            result = agent("Run your analysis cycle now.")
        finally:
            writer.flush()
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        usage = result.metrics.accumulated_usage
        token_parts = [
            f"in={usage.get('inputTokens', 0)}",
            f"out={usage.get('outputTokens', 0)}",
        ]
        if usage.get("cacheReadInputTokens"):
            token_parts.append(f"cache_read={usage['cacheReadInputTokens']}")
        if usage.get("cacheWriteInputTokens"):
            token_parts.append(f"cache_write={usage['cacheWriteInputTokens']}")

        logger.info("Agent '%s' completed. Tokens: %s", name, ", ".join(token_parts))
    except Exception as e:
        logger.error("Agent '%s' failed: %s", name, e)


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP handler for agent webhook triggers.

    Accepts POST /agents/<agent-name> and queues the agent for execution.
    """

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "agents":
            agent_name = parts[1]
            if agent_name in self.server.valid_agents:
                self.server.webhook_queue.put(agent_name)
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "accepted", "agent": agent_name}).encode())
            else:
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"agent '{agent_name}' not found"}).encode())
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "not found"}).encode())

    def do_GET(self):
        self.send_response(405)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "method not allowed, use POST"}).encode())

    def log_message(self, format, *args):
        logger.info("Webhook: %s", format % args)


def start_webhook_server(port: int, valid_agents: set[str], webhook_queue: queue.Queue) -> HTTPServer:
    """Start the webhook HTTP server in a daemon thread."""
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    server.valid_agents = valid_agents
    server.webhook_queue = webhook_queue
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Webhook server listening on 0.0.0.0:%s", port)
    return server


def main():
    setup_logging()

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Parse agent list with per-agent frequencies
    agents_str = os.getenv("SNAKE_AGENTS", "operational-report:24h")
    try:
        agents_config = parse_agents_config(agents_str)
    except ValueError as e:
        logger.error("Error: %s", e)
        return 1

    if not agents_config:
        logger.error("SNAKE_AGENTS is empty. Set it to 'name:frequency' pairs (e.g., 'operational-report:1h,admin-chatbot:10m').")
        return 1

    agents_dir = Path(os.getenv("SNAKE_AGENTS_DIR", "./agents"))
    if not agents_dir.is_dir():
        logger.error("Agents directory not found: %s", agents_dir)
        return 1

    # Set up log directory for agent output
    log_dir = Path(os.getenv("SNAKE_AGENT_LOG_DIR", os.getenv("LOG_DIR", "./logs")))
    log_dir.mkdir(parents=True, exist_ok=True)

    # Set up sessions directory for persistent conversation history
    sessions_dir = Path(os.getenv("SNAKE_SESSIONS_DIR", "./sessions"))
    sessions_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Snake starting...")
    logger.info("Agents directory: %s", agents_dir)
    logger.info("Sessions directory: %s", sessions_dir)
    logger.info("Agent log directory: %s", log_dir)
    for ac in agents_config:
        if ac["frequency"] == "webhook":
            logger.info("  Agent '%s': webhook-triggered, query period: %sm", ac["name"], ac["period_minutes"])
        else:
            logger.info("  Agent '%s': every %s (%ss), query period: %sm", ac["name"], ac["frequency"], ac["interval_seconds"], ac["period_minutes"])

    # Create persistent agent instances (conversation history is preserved across runs)
    agents_by_name = {ac["name"]: ac for ac in agents_config}
    agent_instances: dict[str, Agent] = {}

    for ac in agents_config:
        result = create_agent(ac["name"], agents_dir, ac["period_minutes"], sessions_dir)
        if result is None:
            logger.warning("Skipping agent '%s' due to load failure.", ac["name"])
            continue
        agent_instances[ac["name"]] = result[0]

    if not agent_instances:
        logger.error("No agents could be loaded.")
        return 1

    # Create per-agent loggers with daily file rotation
    agent_loggers: dict[str, logging.Logger] = {}
    for name in agent_instances:
        agent_loggers[name] = setup_agent_logger(name, log_dir)

    # Start webhook server
    webhook_port = int(os.getenv("SNAKE_WEBHOOK_PORT", "8000"))
    webhook_q: queue.Queue[str] = queue.Queue()
    webhook_server = start_webhook_server(webhook_port, set(agent_instances.keys()), webhook_q)

    # Initialize schedule — only for agents with interval-based frequencies
    now = time.time()
    schedule = {
        name: now for name in agent_instances
        if agents_by_name[name]["interval_seconds"] is not None
    }

    while not shutdown_requested:
        # Drain webhook queue — run triggered agents immediately
        while not webhook_q.empty() and not shutdown_requested:
            try:
                agent_name = webhook_q.get_nowait()
            except queue.Empty:
                break
            if agent_name in agent_instances:
                ac = agents_by_name[agent_name]
                logger.info("Webhook triggered agent '%s'", agent_name)
                run_agent(agent_instances[agent_name], agent_name, agents_dir, ac["period_minutes"], log_dir, agent_loggers)

            if shutdown_requested:
                break

        if shutdown_requested:
            break

        # Check scheduled agents
        if schedule:
            next_agent = min(schedule, key=schedule.get)
            next_run = schedule[next_agent]

            if time.time() >= next_run:
                # Run all agents that are due
                now = time.time()
                for name, run_at in sorted(schedule.items(), key=lambda x: x[1]):
                    if shutdown_requested:
                        break
                    if run_at > now:
                        break
                    ac = agents_by_name[name]
                    run_agent(agent_instances[name], name, agents_dir, ac["period_minutes"], log_dir, agent_loggers)
                    schedule[name] = time.time() + ac["interval_seconds"]
            else:
                next_run_time = datetime.fromtimestamp(next_run)
                logger.info("Next up: '%s' at %s", next_agent, next_run_time.isoformat())
                while not shutdown_requested and time.time() < next_run and webhook_q.empty():
                    time.sleep(1)
        else:
            # No scheduled agents — just wait for webhooks
            time.sleep(1)

    webhook_server.shutdown()
    logger.info("Snake stopped.")
    return 0


if __name__ == "__main__":
    exit(main())
