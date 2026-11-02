# Privacy Policy

_Last updated: November 2026_

**Deep Work AI collects nothing.** It has no servers, no accounts, no analytics and no telemetry.
Everything it records stays on your PC, in the `data/` folder of the app, readable only by your
Windows user account.

## What is stored on your PC

| Data | Why | Kept for |
|---|---|---|
| Which app window is in front, its title (redacted), your current repo and branch | Works out what you're doing and your focus score | 14 days |
| Workspace snapshots: open windows, their positions, open browser tabs (secret URL parameters removed) | Restore and Time Travel | Automatic: 14 days. Saved by you: until you delete them |
| Notifications from services you connected (Slack, GitHub, Jira) | Holding them while you focus, and the Inbox | 14 days |
| Your next-step note and context anchor (file and line) | Resume where you left off | Until replaced |
| Focus scores and interruption decisions | Insights | 14 days |
| API tokens you add | Connecting to your own Slack/GitHub/Jira | Until you delete them; encrypted with Windows DPAPI |

Emails, tokens, passwords and long numbers are removed from window titles and URLs before they are
saved. Retention can be changed with `DEEPWORKAI_RETENTION_DAYS`. `DEEPWORKAI_PRIVATE_MODE=1`
stops window titles from being stored and turns off automatic context capture.

## Network connections

Only if you add your own tokens, Deep Work AI talks **directly from your PC** to:
- `slack.com` — Do Not Disturb, status, and your messages
- `api.github.com` — CI status, review requests, notifications
- your Jira site — issues assigned to you

Nothing is sent to the developers of Deep Work AI or anyone else. `DEEPWORKAI_OFFLINE=1` turns all
network access off.

## Deleting your data

Close Deep Work AI and delete the `data/` folder. To remove stored tokens:
`python -m deepworkai.service.secrets_store delete SLACK_TOKEN` (and likewise for the others).

## Contact

Questions: open an issue at https://github.com/viki22uied/Deepworkai/issues
