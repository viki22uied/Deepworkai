# Deep Work AI

**Version 4.0.0 (Beta). Windows 10 and Windows 11 only.**

Deep Work AI is a plugin for the Logitech MX Creative Console. It helps you keep your focus.
Three keys and one dial control all functions. All data stays on your computer.

> This document uses ASD-STE100 Simplified Technical English.

## Contents

1. [What the plugin does](#what-the-plugin-does)
2. [Requirements](#requirements)
3. [Install the plugin](#install-the-plugin)
4. [The Rule of Three: keys and dial](#the-rule-of-three-keys-and-dial)
5. [The Hub](#the-hub)
6. [Connect your accounts](#connect-your-accounts)
7. [Functions](#functions)
8. [Settings](#settings)
9. [Your data and privacy](#your-data-and-privacy)
10. [Security](#security)
11. [Troubleshooting](#troubleshooting)
12. [For developers](#for-developers)
13. [License](#license)
14. [Credits](#credits)

## What the plugin does

- It saves your workspace: open windows, window positions and browser tabs.
- It restores your workspace when you return to your work.
- It holds notifications from GitHub, Slack and Jira while you focus.
- It sorts notifications by priority: HIGH, MEDIUM or LOW.
- It shows what you did earlier and lets you go back to that moment (Time Travel).
- It calculates a focus score from 0 to 100.

The plugin does not send data to the developer. It has no server, no account and no telemetry.

## Requirements

| Item | Requirement |
|---|---|
| Computer | Windows 10 or Windows 11 |
| Device | Logitech MX Creative Console (keypad and dial) |
| Software | Logi Options+ with the Logi Plugin Service |
| Accounts | Optional: GitHub, Slack or Jira |

You do not need Python or Node.js. The plugin package contains the Deep Work AI app.

## Install the plugin

1. Open Logi Options+.
2. Open the Logitech Marketplace.
3. Find **Deep Work AI**.
4. Click **Install**.
5. Select your MX Creative Console in Logi Options+.
6. Put the **Focus**, **Resume** and **Inbox** actions on three keys.
7. Put the **Time Travel** action on the dial.

When you push a key for the first time, the plugin starts the Deep Work AI app.
The app runs in the background. It does not show a console window.

## The Rule of Three: keys and dial

Three keys and one dial control all functions. Push a key one, two or three times quickly.

| Control | Push 1 time | Push 2 times | Push 3 times |
|---|---|---|---|
| **Focus** | Focus Shield on or off | Meeting mode on or off | Save your spot |
| **Resume** | Restore your workspace | Write a next-step note | — |
| **Inbox** | Open the Hub | Queue this interruption | Release all held items |

| Dial | Result |
|---|---|
| Turn left | Go back through the moments of your day |
| Turn right | Go forward to "Now" |
| Push the dial | Restore the selected moment. Windows that were not open at that moment are minimized. |
| Stop turning | Nothing occurs. After 30 seconds, the Hub closes. |

You can also push **Resume** 1 time to restore the selected moment.
If **Now** is selected, **Resume** does its usual restore.
To stop without a restore, turn the dial back to **Now**, or push **Esc**.

If the dial push does not restore, put the **Restore moment** action on the dial push or on a key.

A small message shows at the bottom of the screen after each key push without a window.
For example: "Focus Shield ON", "Focus Shield OFF", "Meeting mode ON" or "Spot saved".

### Focus

- **Push 1 time.** This turns the Focus Shield on or off. The plugin saves your workspace first.
  While the shield is on, the plugin holds notifications in the Inbox.
- **Push 2 times.** This turns Meeting mode on or off. Meeting mode saves your workspace.
  When the meeting ends, the plugin restores your workspace.
- **Push 3 times.** This saves your spot: your windows, tabs and the file you work on.

### Resume

- **Push 1 time.** The plugin restores your last saved spot.
  It opens your browsers with the saved tabs.
  It moves your windows back to their saved positions.
  Then it opens your editor at the saved file and line, if you saved one.
- **Push 2 times.** You can write a short note about your next step.

### Inbox

- **Push 1 time.** This opens the Hub. If items are in the Inbox, the Hub shows the Inbox.
- **Push 2 times.** This puts the current interruption in a queue for later.
- **Push 3 times.** This releases all held notifications.

## The Hub

The Hub is the only window of the plugin. It has four pages.

| Page | Contents |
|---|---|
| **Focus** | Your activity, your focus score, your next-step note and quick commands |
| **Time Travel** | A list of saved moments. Each moment shows the open windows and browser tabs. "Now" shows the windows that are open at this time. |
| **Inbox** | Held notifications, sorted by priority. The **Accounts** panel connects your accounts. |
| **Insights** | Your best focus hours, your deep-work time and who interrupts you |

Keys in the Hub: push **1** to **4** to change the page. Push **Esc** to hide the Hub.
The Hub stays ready in the background, so it opens immediately.

## Connect your accounts

The Inbox gets items only from accounts that you connect.
The plugin collects notifications only while the Focus Shield is on.

1. Push **Inbox** 1 time.
2. Click **Accounts**.
3. Get a token from the service (see the table).
4. Paste the token in the field.
5. Click **Connect**.

| Service | Token | Where to get it |
|---|---|---|
| GitHub | Personal access token (classic) with the **notifications** scope. Add **repo** for private repositories. | github.com > Settings > Developer settings > Personal access tokens > Tokens (classic) |
| Slack | User OAuth token (`xoxp-…`) | api.slack.com/apps > your app > OAuth & Permissions |
| Jira | Site address, account email and API token | id.atlassian.com > Security > API tokens |

**CAUTION:** Use a **classic** GitHub token. A fine-grained token cannot read notifications.
The Accounts panel tests the GitHub token. It tells you if the token cannot read notifications.

The plugin encrypts each token immediately. Only your Windows account can decrypt it.
The plugin does not show the token again. Click **Remove** to delete a token.

GitHub does not send you notifications about your own actions.
Mentions, review requests and comments from other people appear in the Inbox.

## Functions

### Workspace save and restore

The plugin saves:

- The open windows and their positions.
- The open tabs of Chrome, Edge, Brave, Vivaldi, Opera and Firefox, in all profiles.
- The file and line in your editor, if you saved your spot.

When the plugin restores a workspace:

1. It opens each browser that was open. A browser that runs only in the background counts as closed.
2. It opens only the saved tabs that are not already open. It does not open a tab two times.
3. It starts the other apps that were open.
4. It moves each window to its saved position. It moves new windows again after 2 seconds.

Brave locks its tab file while it runs. The plugin then reads the tab list at restore time,
up to the moment of the save. The plugin cannot close tabs in a browser.

A Time Travel restore also minimizes the windows that were not open at that moment.
It does not close them. Use the taskbar to show them again. **Resume** does not minimize windows.

The plugin never starts a second copy of itself. It does not restart Logitech or system processes.

### Focus Shield

When the shield is on, the plugin:

- Holds notifications from your connected accounts in the Inbox.
- Sets Slack to Do Not Disturb, if you connected Slack.

The shield does not close apps or windows. To also close distracting apps, see [Settings](#settings).

### Inbox and priority

A local classifier gives each notification a priority: HIGH, MEDIUM or LOW.
The plugin holds an item, puts it in a batch for later, or lets it through.
The decision uses the priority and your focus score.

### Focus score

The focus score (0 to 100) uses the last 30 minutes of activity:

| Part | Weight | Measure |
|---|---|---|
| Work apps | 45% | Time in editors, terminals and AI coding apps. Browser time counts half. |
| Few app switches | 30% | The score falls quickly above 6 switches in 10 minutes. |
| Long work period | 25% | Full value after 25 minutes without a break. |

The score is half when you are in a chat app or a meeting.

The plugin finds your current project from your editor, or from the folder of your terminal or AI coding app.

### Quick commands

The Focus page has six quick commands. Each command opens a terminal in your current project.
The default commands are `npm test`, `npm run dev`, `docker compose up --build`, `git push`,
`git pull --rebase` and `docker compose logs -f`.
To change the commands, edit `%LOCALAPPDATA%\DeepWorkAI\data\palette.json`.

### Debugger on the dial

During a VS Code debug session, the dial steps through your code.
The plugin sends the debugger keys only when VS Code or Cursor is the active window.

## Settings

Set these Windows environment variables to change the behavior. All are optional.

| Variable | Default | Result |
|---|---|---|
| `DEEPWORKAI_OFFLINE` | `0` | `1` stops all network connections. |
| `DEEPWORKAI_PRIVATE_MODE` | `0` | `1` stops the save of window titles and stops automatic context saves. |
| `DEEPWORKAI_RETENTION_DAYS` | `14` | Number of days before the plugin deletes old data. |
| `DEEPWORKAI_BLOCK_DISTRACTIONS` | `0` | `1` lets the Focus Shield close distracting apps and windows. |
| `DEEPWORKAI_UI_KEEPALIVE_MIN` | `0` | Minutes before a hidden Hub closes. `0` keeps it ready. |

**WARNING:** `DEEPWORKAI_BLOCK_DISTRACTIONS=1` closes apps such as Spotify, Discord, WhatsApp and Steam.
It also closes windows with YouTube, Netflix or Reddit in the title. This closes a full browser
window with all its tabs. Save your work before you use this setting.

## Your data and privacy

- All data stays on your computer in `%LOCALAPPDATA%\DeepWorkAI\data`.
- Only your Windows account can read this folder.
- The plugin removes emails, tokens and secret URL parameters before it saves titles and URLs.
- The logs contain only command names and results. They do not contain titles, URLs, notes or tokens.
- The plugin deletes old data after 14 days. You can change this value.

To delete all data:

1. Uninstall the plugin in Logi Options+.
2. Delete the folder `%LOCALAPPDATA%\DeepWorkAI`.

For more information, read [PRIVACY.md](PRIVACY.md).

## Security

- The app accepts connections only from your own computer.
- Each command needs a random session key. Only your Windows account can read the key.
- Windows DPAPI encrypts your tokens for your Windows account.
- Only one copy of the app can run. Four launches at the same time give one service and one Hub.
- The plugin does not act on its own. Restores and app starts occur only after a key push or a dial turn.

For the full security model and how to report a vulnerability, read [SECURITY.md](SECURITY.md).

## Troubleshooting

| Problem | Cause | Action |
|---|---|---|
| The plugin is not in Logi Options+. | An old development link points to a deleted folder. | Remove the `DeepWorkAi` entry from `%LOCALAPPDATA%\Logi\LogiPluginService\Plugins`. Then install the plugin again. |
| Keys do nothing. | The app is not running. | Push a key again. The plugin starts the app. |
| The Inbox is empty. | No account is connected, or the Focus Shield is off. | Connect an account. Turn on the Focus Shield. |
| GitHub items do not appear. | The token is fine-grained. | Use a classic token with the **notifications** scope. |
| A restore opened old tabs. | The browser restored its own last session. | Close the extra tabs. The plugin cannot close tabs. |
| The dial push does not restore. | Logi Options+ did not assign the dial push. | Put the **Restore moment** action on the dial push, or push **Resume**. |

The logs are in `%LOCALAPPDATA%\DeepWorkAI\data\service.log` and
`%LOCALAPPDATA%\Logi\LogiPluginService\Plugins\debug.log`.

## For developers

### Project structure

| Folder | Contents |
|---|---|
| `deepworkai/plugin` | The Logitech plugin (Node.js): keys, dial and app start |
| `deepworkai/service` | The background service: commands, restore, browser tabs, token vault |
| `deepworkai/features` | Focus Shield, Inbox, classifier, meeting mode, anchor, quick commands |
| `deepworkai/activity` | The activity recorder: active app and current project |
| `deepworkai/ui` | The Hub and Time Travel |
| `packaging` | The Windows build: PyInstaller recipe, build script and smoke test |
| `tests` | The test suite |

### Run from source

1. Install Python 3.10 or later.
2. Clone the repository:
   ```bash
   git clone https://github.com/viki22uied/Deepworkai.git
   ```
3. Install the Python packages:
   ```bash
   pip install -r requirements.txt
   ```
4. Start the service:
   ```bash
   python deepworkai/service/deepwork_service.py
   ```
5. Link the plugin to Logi Options+ for development:
   ```bash
   cd deepworkai/plugin
   npm install
   npm run build
   npm run link
   ```

When you run from source, the data is in the `data` folder of the repository.

### Run the tests

```bash
python -m pytest -q tests
```

The tests cannot start programs, open a browser or push keys on your computer.
A guard in `tests/conftest.py` stops each attempt.

### Build the Marketplace package

Run this command in PowerShell from the repository root:

```powershell
.\packaging\build-windows.ps1
```

The script does these steps:

1. It installs the Python packages and PyInstaller.
2. It builds `build/app/DeepWorkAI/DeepWorkAI.exe`.
3. It runs the smoke test. The test checks the service, the session key, the logs and the single-copy rule.
4. It builds `deepworkai/plugin/DeepWorkAi.lplug4`, with the app inside.

Make sure that no other copy of Deep Work AI runs before you start the build.
GitHub Actions also builds the package for each `v*` tag.

## License

Deep Work AI is free software under the [MIT License](LICENSE).
Your use of the plugin is also subject to the [End User License Agreement](EULA.md).
The plugin is not made, endorsed or supported by Logitech.

## Credits

Built by the **Deep Work AI team**.

Deep Work AI was a **Top 50** project in the **Logitech DevStudio Hackathon**.
The team was a **semi-finalist**.
