---
tools:
  - get_rust_server_logs
  - post_discord_admin_alert
  - save_report_html
model: claude-sonnet-4-20250514
max_tokens: 4096
---

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

## Avoiding Duplicate Discord Alerts

Your conversation history persists across analysis cycles. Use it to track which incidents you have already reported to Discord. Do NOT post a Discord alert for an incident you have already reported in a previous cycle. Only post a new alert for the same incident if there is significant new information (e.g., new players involved, escalation in severity, new details that change the priority or nature of the report). Routine follow-up chat about an already-reported topic does not warrant a new alert.