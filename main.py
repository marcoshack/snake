from dotenv import load_dotenv
from strands import Agent
from strands.models.anthropic import AnthropicModel
from tools import get_rust_server_logs, post_discord_admin_alert, save_report_html

load_dotenv()

# Create an agent using Anthropic API directly
model = AnthropicModel(model_id="claude-sonnet-4-20250514", max_tokens=4096)
agent = Agent(model=model, tools=[get_rust_server_logs, post_discord_admin_alert, save_report_html])

# Ask the agent to analyze the Rust server logs
agent("""
Fetch the server logs from the Rust game server for the last 24 hours.

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