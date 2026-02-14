import os
import re
import signal
import sys
import time
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from strands import Agent
from strands.models.anthropic import AnthropicModel
from tools import get_rust_server_logs, post_discord_admin_alert, save_report_html

load_dotenv()

# Flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    print(f"\n[{datetime.now().isoformat()}] Received signal {signum}, shutting down gracefully...")
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


def run_analysis(agent: Agent, period_minutes: int, log_dir: Path) -> None:
    """Run a single analysis cycle for the specified period."""
    print(f"[{datetime.now().isoformat()}] Starting analysis for the last {period_minutes} minutes...")

    # Calculate hours from minutes (rounding up to ensure we get all logs)
    period_hours = max(1, int((period_minutes + 59) / 60))

    # Create a log file for this analysis run
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    agent_log_file = log_dir / f"agent_log_{timestamp}.txt"

    try:
        # Redirect agent output (both stdout and stderr) to log file
        with open(agent_log_file, 'w') as f:
            with redirect_stdout(f), redirect_stderr(f):
                agent(f"""
Fetch the server logs from the Rust game server by calling get_rust_server_logs(hours={period_hours}).
This will fetch logs for approximately the last {period_minutes} minutes.

Analyze the logs focusing on:
1. **Period & Activity Level**: Time range and overall activity
2. **Cheating Detection**: Look carefully for:
   - Anti-cheat violations or suspicious behavior in server logs
   - Players discussing cheating (hacks, aimbots, exploits) in chat
   - Unusual kill patterns or impossible actions
3. **Technical Issues**: Server errors, crashes, performance problems
4. **Notable Incidents**: Admin actions, rule violations

After analysis, ALWAYS post to Discord:
- If everything is normal: Post a brief status update (1-2 sentences)
- If there are security concerns or urgent issues: Post the FULL detailed analysis including player names, timestamps, and specific evidence

Security concerns that require full analysis:
- Cheating attempts (confirmed or suspected)
- Technical problems affecting gameplay
- Serious rule violations

Finally, save the full report as an HTML file for archival.
""")
        print(f"[{datetime.now().isoformat()}] Analysis completed successfully.")
        print(f"[{datetime.now().isoformat()}] Agent output saved to: {agent_log_file.name}")
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Analysis failed with error: {e}")


def main():
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Parse the analysis frequency
    frequency_str = os.getenv("ANALYSIS_FREQUENCY", "24h")
    try:
        interval_seconds = parse_duration(frequency_str)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Calculate analysis period with 10% buffer
    period_minutes = int((interval_seconds / 60) * 1.1)

    # Set up log directory for agent output
    log_dir = Path(os.getenv("LOG_DIR", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{datetime.now().isoformat()}] Snake agent starting...")
    print(f"[{datetime.now().isoformat()}] Analysis frequency: {frequency_str} ({interval_seconds} seconds)")
    print(f"[{datetime.now().isoformat()}] Analysis period: {period_minutes} minutes (includes 10% buffer)")
    print(f"[{datetime.now().isoformat()}] Agent output will be logged to: {log_dir}")

    # Create the agent
    model = AnthropicModel(model_id="claude-sonnet-4-20250514", max_tokens=4096)
    agent = Agent(model=model, tools=[get_rust_server_logs, post_discord_admin_alert, save_report_html])

    # Run the first analysis immediately
    run_analysis(agent, period_minutes, log_dir)

    # Continue running periodically until shutdown is requested
    while not shutdown_requested:
        next_run = datetime.now().timestamp() + interval_seconds
        next_run_time = datetime.fromtimestamp(next_run)
        print(f"[{datetime.now().isoformat()}] Next analysis scheduled for: {next_run_time.isoformat()}")

        # Sleep in small increments to allow for graceful shutdown
        while not shutdown_requested and time.time() < next_run:
            time.sleep(1)

        if not shutdown_requested:
            run_analysis(agent, period_minutes, log_dir)

    print(f"[{datetime.now().isoformat()}] Snake agent stopped.")
    return 0


if __name__ == "__main__":
    exit(main())