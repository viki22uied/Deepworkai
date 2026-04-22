# Deep Work AI — Cognitive Focus Operating System

> **Built for developers who need to stay in the zone.**
> Deep Work AI transforms the **Logitech MX Creative Console** into a hardware-native focus engine — capturing workspaces, silencing distractions, surfacing only what matters, and letting you time-travel back to your last deep state.

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration (.env)](#configuration-env)
5. [Features In-Depth](#features-in-depth)
   - [Workspace Capture & Restore (Sphere Re-Threading)](#1-workspace-capture--restore-sphere-re-threading)
   - [Focus Shield](#2-focus-shield)
   - [Cognitive Rewind](#3-cognitive-rewind)
   - [Triage Dashboard](#4-triage-dashboard)
   - [Notification Classifier (AI Priority Engine)](#5-notification-classifier-ai-priority-engine)
   - [Meeting Mode](#6-meeting-mode)
   - [Micro-Journal](#7-micro-journal)
   - [Context Anchor](#8-context-anchor)
   - [Smart Interruption Queue](#9-smart-interruption-queue)
   - [Blocker Radar (CI/GitHub Status)](#10-blocker-radar-cigithub-status)
   - [Git Branch Pulse](#11-git-branch-pulse)
   - [Terminal Command Palette](#12-terminal-command-palette)
   - [Focus Depth Timer](#13-focus-depth-timer)
   - [Debug Surface](#14-debug-surface)
6. [Architecture](#architecture)
7. [TCP Command Reference](#tcp-command-reference)
8. [Logitech Plugin Setup](#logitech-plugin-setup)
9. [Running the Service](#running-the-service)
10. [Slack Integration](#slack-integration)
11. [Project Structure](#project-structure)
12. [Troubleshooting](#troubleshooting)

---

## Overview

Deep Work AI is a **Windows-only** background service that runs silently on your machine and connects your **Logitech MX Creative Console** hardware (keypad + dial) to a suite of developer-focused features via a local TCP socket (`127.0.0.1:57321`).

Every action you'd normally hunt for in a menu — save your workspace, silence Slack, check if CI is green, jot a quick thought — is a single button press on your hardware. No terminal windows, no popups, no friction.

---

## Prerequisites

### Hardware

| Requirement | Notes |
|---|---|
| **Logitech MX Creative Console** | The keypad + dial hardware that this system is built for |

### Software

| Requirement | Version | Notes |
|---|---|---|
| **Windows 10/11** | Any recent build | The service uses `pywin32`, Windows Task Scheduler, and `wt.exe` |
| **Python** | 3.10 or higher | Must be on your system `PATH` |
| **Node.js + npm** | 16+ recommended | Required to build the Logitech plugin bridge |
| **Logitech Options+** | Latest | The official companion app for the MX Creative Console |
| **Git** | Any recent version | Required for Blocker Radar, Git Pulse, and Cognitive Rewind features |
| **Windows Terminal (`wt.exe`)** | Latest | Required for the Terminal Command Palette; falls back to plain PowerShell if missing |

### Optional Integrations

These are not required — the system degrades gracefully without them:

| Integration | What it unlocks |
|---|---|
| **Slack Bot Token** | Focus Shield sets/clears DND, Meeting Mode status, context restore |
| **GitHub Personal Access Token** | Blocker Radar (CI status, PR count, branch health) and Git Pulse haptic alerts |
| **Jira API Token** | Notification interceptor can pull Jira ticket updates into the Triage Dashboard |

---

## Installation

### Step 1 — Clone the Repository

```bash
git clone https://github.com/viki22uied/Deep.git
cd Deep
```

### Step 2 — Install Python Dependencies

```bash
pip install -r requirements.txt
```

This installs:

| Package | Purpose |
|---|---|
| `pywin32 >= 306` | Windows window management APIs (enumerate windows, restore positions) |
| `psutil >= 5.9.0` | Process detection, freezing, and CPU priority management |
| `requests >= 2.31.0` | HTTP calls to Slack, GitHub, and Jira APIs |
| `PyQt6 >= 6.5.0` | Micro-journal overlay UI (frameless input box) |
| `scikit-learn >= 1.3.0` | TF-IDF + Logistic Regression notification priority classifier |
| `python-dotenv >= 1.0.0` | Loads your `.env` file at startup |
| `pyautogui >= 0.9.54` | Debug surface keyboard shortcut injection |

### Step 3 — Configure Your Environment

Copy the example environment file and fill in your tokens:

```bash
copy .env.example .env
```

Edit `.env` with your actual values (see [Configuration](#configuration-env) below).

### Step 4 — Install and Register the Service

```bash
python install.py
```

This script:
- Registers the Deep Work AI background service as a **Windows Task Scheduler task** (auto-starts at login)
- Builds and links the Logitech plugin so it appears in Options+
- Creates the `data/` directory and initial databases

> **Admin privileges are required** for this step in order to register the scheduled task.

### Step 5 — Enable Developer Mode in Logitech Options+

1. Open **Logi Options+**
2. Go to **Settings** → enable **Developer Mode**

### Step 6 — Assign Actions to Your Console

1. In Options+, select your **MX Creative Console**
2. The **Deep Work AI** plugin should appear in the "All Actions" panel
3. Drag actions (Capture, Restore, Focus Shield, Rewind, Journal, etc.) onto your keypad buttons or dial

---

## Configuration (.env)

Create a `.env` file in the project root. All fields are optional — the system will run without any of them, with affected features silently degraded.

```env
# ── Slack ──────────────────────────────────────────────────────────────────────
# Get from: https://api.slack.com/apps → OAuth & Permissions → Bot Token
# Required scopes: dnd:write, dnd:read, users.profile:write
SLACK_TOKEN=xoxp-your-token-here

# ── GitHub ─────────────────────────────────────────────────────────────────────
# Get from: https://github.com/settings/tokens → Classic → repo + notifications
GITHUB_TOKEN=ghp_your_token_here
# Format: owner/reponame  e.g. acmecorp/backend-api
GITHUB_REPO=your-org/your-repo

# ── Jira (optional) ────────────────────────────────────────────────────────────
# JIRA_EMAIL=you@company.com
# JIRA_TOKEN=your-atlassian-api-token
# JIRA_URL=https://yourcompany.atlassian.net

# ── Email (optional) ───────────────────────────────────────────────────────────
# IMAP_SERVER=imap.gmail.com
# IMAP_EMAIL=your.email@gmail.com
# IMAP_PASSWORD=your-app-password

# ── Dev ────────────────────────────────────────────────────────────────────────
DEBUG=true
LOG_LEVEL=INFO
```

---

## Features In-Depth

### 1. Workspace Capture & Restore (Sphere Re-Threading)

**What it does:** Snapshots your entire working environment — every open application, browser tabs, window positions and sizes, active git branch — into a timestamped JSON capsule stored in a local SQLite database. A single button press restores you to that exact state.

**How it works:**
- `deep_restore_core.py` enumerates all visible windows using `pywin32`, records their positions and sizes, and queries the browser for open tabs
- Snapshots are saved to `data/capsules.db` with a timestamp and label
- On restore, windows are re-opened, repositioned, and browsers are directed back to the saved tabs

**Relevant commands:** `CAPTURE`, `RESTORE`, `REWIND:<minutes>`

**Use case:** You're mid-debug and have to jump to a hotfix. Capture → switch → restore when you come back.

---

### 2. Focus Shield

**What it does:** A one-button distraction eliminator. When activated:
- Sets your Slack status to **Do Not Disturb**
- Freezes or deprioritizes non-essential processes
- Suppresses system notifications
- All incoming notifications are held in the Triage Dashboard instead of interrupting you

**How it works:**
- `focus_mode.py` records the session start time in `activity.db`
- `slack_integration.py` calls the Slack `dnd.setSnooze` API using your `SLACK_TOKEN`
- Notifications are intercepted by `notification_interceptor.py` and routed to the holding tank
- Shield state is persisted to disk so restarts don't break an active session

**Relevant commands:** `SHIELD_ON`, `SHIELD_OFF`, `SHIELD_TOGGLE`

---

### 3. Cognitive Rewind

**What it does:** Builds a high-signal summary of what you were doing in the last 5, 15, or 30 minutes, displayed as a compact overlay. This includes:
- Active git repo, branch, and recently changed files
- Last file open in VS Code / Cursor (extracted from window title)
- Developer-relevant browser tabs (GitHub, GitLab, Jira, Stack Overflow, localhost — social and irrelevant tabs are filtered out)
- Your last Micro-Journal next-step note

**How it works:**
- `cognitive_rewind.py` queries `activity.db` for events in the requested time window
- A curated `DEVELOPER_DOMAINS` allowlist filters browser history to only what is relevant to engineering work
- The context dict is rendered on the LCD display or in an overlay

**Relevant command:** `COGNITIVE_REWIND`, `REWIND:<N>`

**Use case:** You get pulled into a 30-minute Slack fire drill. When you come back, one button press re-orients you instantly.

---

### 4. Triage Dashboard

**What it does:** Opens a rich dark-mode GUI ("Holding Tank") showing every notification that arrived during a Focus Shield session, sorted by AI-assigned priority (HIGH → MEDIUM → LOW). You review them all at once when you surface from deep work, not one-by-one during it.

**How it works:**
- Built with `tkinter` (no extra dependencies)
- Pulls all unreviewed notifications from `data/notifications.db` via the classifier module
- Displays source (Slack / Jira / GitHub), sender, channel, body, confidence score, and relative arrival time
- Supports filtering by priority level: `--filter HIGH`
- Includes a `--demo` mode with realistic sample data for setup testing

**Relevant command:** `TRIAGE_SHOW`

**Run standalone:**
```bash
python deepworkai/features/triage_dashboard.py
python deepworkai/features/triage_dashboard.py --filter HIGH
python deepworkai/features/triage_dashboard.py --demo
```

---

### 5. Notification Classifier (AI Priority Engine)

**What it does:** Every incoming notification is classified as `LOW`, `MEDIUM`, or `HIGH` priority before being stored. The Focus Shield uses this classification to decide whether to hold a notification silently or surface it immediately.

**How it works (two-stage pipeline):**

1. **Rule-based fast path** — Regex and keyword matching catches obvious cases instantly (e.g., "URGENT", "PROD down", your name mentioned, direct messages)
2. **TF-IDF + Logistic Regression** — A scikit-learn model trained on bootstrap-labelled notification data classifies anything the rules don't catch confidently
3. **Confidence threshold** — Anything below 60% confidence falls back to `MEDIUM`

**Graceful degradation:** If `scikit-learn` is not installed, the system falls back to rules-only classification without crashing.

**Storage:** All notifications are persisted in `data/notifications.db` with full metadata: source, title, body, sender, channel, URL, priority, confidence score, arrival time, and reviewed/held flags.

---

### 6. Meeting Mode

**What it does:** A dedicated single-button in/out for meetings that handles everything automatically:

- **On entry:** Saves a workspace snapshot labelled `"meeting"`, sets Slack DND, starts an elapsed-time counter on the LCD display
- **On exit:** Restores the saved workspace snapshot, clears DND, shows your last Micro-Journal note as a re-orientation reminder, displays total meeting duration

**How it works:**
- `meeting_mode.py` orchestrates `deep_restore_core`, `slack_integration`, `lcd_state`, and `micro_journal`
- A background thread updates the LCD every 30 seconds with elapsed meeting time
- State is persisted to `data/meeting_state.json` so the timer survives service restarts

**Relevant commands:** `MEETING_TOGGLE`, `MEETING_START`, `MEETING_END`

---

### 7. Micro-Journal

**What it does:** A hardware-triggered, frameless single-line input overlay. Press the button and a minimal text box appears over your current window. Type your next-step thought and press Enter — it vanishes and saves your note. The note is surfaced by Cognitive Rewind and Meeting Mode exit.

**How it works:**
- `micro_journal.py` spawns the overlay as a fresh `pythonw.exe` subprocess each time, so it always opens correctly even after being closed
- The overlay (`_journal_overlay.py`) is a borderless PyQt6 window
- Notes are saved as plain text in `data/next_step.txt` (one note at a time — always overwrites)

**Relevant commands:** `JOURNAL_CAPTURE`, `JOURNAL_SAVE:<text>`, `JOURNAL_GET`, `JOURNAL_CLEAR`

---

### 8. Context Anchor

**What it does:** Saves your exact cursor position (file path + line number) inside VS Code or Cursor IDE, then restores you to that exact location with a button tap.

**How it works:**
- **Save (hold button 800ms):** Probes VS Code / Cursor via their CLI (`code --status` or `cursor --status`) to get the active file and line. Falls back to reading `workspaceStorage` JSON files in `AppData/Roaming`. Saves to `data/context_anchor.json`
- **Restore (tap button):** Opens the saved file at the saved line using `code --goto file:line` or `cursor --goto file:line`

**Relevant commands:** `ANCHOR_SAVE`, `ANCHOR_RESTORE`

**Use case:** You're deep in a file and need to quickly look something up elsewhere. Anchor → explore → restore to exact line.

---

### 9. Smart Interruption Queue

**What it does:** When you're interrupted mid-focus but can't fully context-switch, press the Queue button to log the interruption with a timestamp and optional note. The pending count is shown live on the LCD. Review and clear the queue when you have a moment.

**How it works:**
- `smart_queue.py` persists items to `data/queue.db` (SQLite)
- Every `add_item_and_sync` call pushes the updated count to `lcd_state.py` for the LCD display
- `clear_reviewed_and_sync` removes processed items and refreshes the LCD count

**Relevant commands:** `QUEUE_ADD`, `QUEUE_NOTE:<text>`, `QUEUE_LIST`, `QUEUE_CLEAR`

---

### 10. Blocker Radar (CI/GitHub Status)

**What it does:** Polls your GitHub repository every 60 seconds and shows ambient status on the LCD — no popups, no sounds. You always know at a glance whether CI is passing, how many PRs need your review, and how many commits behind `main` your branch is.

**What it tracks:**
- **CI Status:** `pass` / `pending` / `fail` / `unknown` — from the latest check-runs on your current branch
- **PR Count:** Number of open pull requests where you are a requested reviewer
- **Branch Health:** How many commits behind `main` or `master` your current branch is
- **Blocked flag:** Automatically set to `true` if CI is failing or you're >10 commits behind

**Requires:** `GITHUB_TOKEN` and `GITHUB_REPO` in `.env`

**State file:** `data/radar_state.json` (so last known state survives restarts)

---

### 11. Git Branch Pulse

**What it does:** Monitors your current git branch's remote for new pushes every 90 seconds. When a teammate pushes to your branch, the Logitech hardware fires a **haptic pulse** — a physical buzz in your hand — with zero visual interruption.

**How it works:**
- `git_pulse.py` runs `git fetch origin <branch>` silently in the background
- Compares the remote hash against its last known value
- On change, sends `HAPTIC_PULSE:2` to the TCP service, which forwards it to the hardware plugin via the Node.js bridge

**No configuration required** — reads the git repo from your working directory automatically.

---

### 12. Terminal Command Palette

**What it does:** 6 configurable one-press terminal commands mapped to LCD button slots. Each press opens a new Windows Terminal tab (or PowerShell window as fallback) running the assigned command.

**Default palette:**

| Slot | Label | Command |
|---|---|---|
| 0 | Tests | `npm test` |
| 1 | Dev | `npm run dev` |
| 2 | Build | `docker compose up --build` |
| 3 | Push | `git push` |
| 4 | Pull | `git pull --rebase` |
| 5 | Logs | `docker compose logs -f` |

**Customizing:** Edit `data/palette.json` to replace any slot with your own label and command.

**Relevant command:** `PALETTE:<slot_index>` (e.g., `PALETTE:0`)

---

### 13. Focus Depth Timer

**What it does:** Counts up silently from zero when a focus session starts. The elapsed time (in minutes) is updated on the LCD display every minute, showing you exactly how long you've been in the zone — and how costly it is to break it.

**How it works:**
- `focus_timer.py` runs a `threading.Thread` as a daemon
- Updates `lcd_state.py` every 60 seconds with elapsed minutes
- Automatically sets LCD mode to `"focus"` on start and clears it on end

---

### 14. Debug Surface

**What it does:** Maps the MX Creative Console dial and buttons to IDE debug shortcuts (F5, F10, F11, Shift+F11, etc.) via `pyautogui`. One dial click steps through code; a button restarts the debugger.

**Relevant command:** `DEBUG_ACTION:<n>`

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Logitech MX Creative Console               │
│              (Physical keypad + dial hardware)               │
└──────────────────────────┬──────────────────────────────────┘
                           │ USB/Bluetooth
┌──────────────────────────▼──────────────────────────────────┐
│                     Logitech Options+                        │
│              (Official companion desktop app)                │
└──────────────────────────┬──────────────────────────────────┘
                           │ Plugin API
┌──────────────────────────▼──────────────────────────────────┐
│           deepworkai/plugin/ (Node.js bridge)                │
│   index.js  ·  tcp-client.js  ·  adjustment-actions.js      │
│          Translates hardware events → TCP commands           │
└──────────────────────────┬──────────────────────────────────┘
                           │ TCP  127.0.0.1:57321
┌──────────────────────────▼──────────────────────────────────┐
│        deepworkai/service/deepwork_service.py                │
│              (Core Python TCP socket server)                 │
│   Command router · Shield state · Process orchestration      │
└────┬───────────┬────────────┬────────────┬──────────────────┘
     │           │            │            │
  Features   Slack        Activity     lcd_state.py
  Modules    Integration  Recorder     (LCD display sync)
     │
     ├── workspace_restore.py  ──► deep_restore_core.py
     ├── focus_mode.py
     ├── focus_timer.py
     ├── cognitive_rewind.py
     ├── triage_dashboard.py  (spawned as subprocess)
     ├── notification_classifier.py
     ├── notification_interceptor.py
     ├── meeting_mode.py
     ├── micro_journal.py  ──► _journal_overlay.py (subprocess)
     ├── context_anchor.py
     ├── smart_queue.py
     ├── blocker_radar.py
     ├── git_pulse.py
     ├── terminal_palette.py
     └── debug_surface.py
```

**Key architectural decisions:**
- **TCP Socket Server** — All hardware commands are plain text over `127.0.0.1:57321`. This keeps the Node.js plugin layer thin and lets you test any command with `nc` or PowerShell.
- **Zero-Terminal Architecture** — All Python processes are spawned with `CREATE_NO_WINDOW` or via `pythonw.exe` so no console windows ever appear.
- **Subprocess isolation** — The Triage Dashboard and Micro-Journal overlay run as child processes so their GUI event loops don't block the main service.
- **SQLite everywhere** — Activity events, notifications, snapshots, and queue items are all stored locally in `data/*.db`. No cloud, no external database.

---

## TCP Command Reference

All commands are plain UTF-8 strings terminated with `\n`. Send them to `127.0.0.1:57321`.

| Command | Description |
|---|---|
| `PING` | Health check — returns `PONG` |
| `STATUS` | Returns a JSON dump of current service state |
| `CAPTURE` | Snapshot current workspace to database |
| `RESTORE` | Restore the most recent workspace snapshot |
| `REWIND:<N>` | Restore the snapshot from N minutes ago |
| `SHIELD_ON` | Activate Focus Shield (DND + notification hold) |
| `SHIELD_OFF` | Deactivate Focus Shield |
| `SHIELD_TOGGLE` | Toggle Focus Shield on/off |
| `TRIAGE_SHOW` | Open the Triage Dashboard window |
| `MEETING_START` | Enter Meeting Mode |
| `MEETING_END` | Exit Meeting Mode |
| `MEETING_TOGGLE` | Toggle Meeting Mode |
| `ANCHOR_SAVE` | Save current cursor position (file + line) |
| `ANCHOR_RESTORE` | Restore IDE to saved file:line |
| `JOURNAL_CAPTURE` | Open Micro-Journal overlay |
| `JOURNAL_SAVE:<text>` | Save a note directly (no overlay) |
| `JOURNAL_GET` | Return current saved note |
| `JOURNAL_CLEAR` | Clear the saved note |
| `QUEUE_ADD` | Log an interruption to the queue |
| `QUEUE_NOTE:<text>` | Log interruption with a note |
| `QUEUE_LIST` | Return list of pending queue items |
| `QUEUE_CLEAR` | Clear reviewed queue items |
| `PALETTE:<N>` | Run terminal palette slot 0–5 |
| `DEBUG_ACTION:<N>` | Fire debug keyboard shortcut N |
| `COGNITIVE_REWIND` | Return context summary as JSON |
| `HAPTIC_PULSE:<N>` | Trigger N haptic pulses on hardware |
| `NOTIF_ADD:<src>\|<title>\|<body>` | Manually inject a notification |
| `OPEN_TRASH` | Open the Windows Recycle Bin |

**Testing a command manually (PowerShell):**
```powershell
$tcp = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 57321)
$writer = New-Object System.IO.StreamWriter($tcp.GetStream())
$writer.WriteLine("PING")
$writer.Flush()
```

---

## Logitech Plugin Setup

The plugin lives in `deepworkai/plugin/` and is a Node.js package built with esbuild.

### Install plugin dependencies

```bash
cd deepworkai/plugin
npm install
```

### Build the plugin

```bash
npm run build
```

### Link plugin to Logitech Options+

```bash
npm run link
```

This creates a symlink from the built plugin to the Logi Plugin Service plugin folder. The plugin should now appear under "All Actions" in Options+.

### Unlink (remove from Options+)

```bash
npm run unlink
```

### Package for distribution

```bash
npm run build:pack
```

Produces a `.lplug4` file suitable for marketplace submission or sharing.

---

## Running the Service

### Automatic (recommended)

After running `install.py`, the service starts automatically at Windows login via Task Scheduler. No action needed.

### Manual start

```bash
python start.py
```

`start.py` launches all components:
- `deepwork_service.py` — TCP server (subprocess, hidden window)
- `recorder.py` — Activity event recorder (subprocess, hidden window)
- `blocker_radar.py` — GitHub CI/PR polling (in-process daemon thread)
- `git_pulse.py` — Branch push detector (in-process daemon thread)
- `debug_surface.py` — Debug shortcut watcher (in-process daemon thread)

### Manual component start (individual modules)

```bash
python deepworkai/service/deepwork_service.py
python deepworkai/features/triage_dashboard.py
```

---

## Slack Integration

To enable full Slack integration:

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Under **OAuth & Permissions**, add the following bot token scopes:
   - `dnd:write` — Set/clear Do Not Disturb
   - `dnd:read` — Check DND status
   - `users.profile:write` — Update status message
3. Install the app to your workspace
4. Copy the **Bot User OAuth Token** (`xoxb-...`) into your `.env` as `SLACK_TOKEN`

**What Slack integration enables:**
- Focus Shield automatically sets and clears Slack DND
- Meeting Mode sets your Slack status to show you're in a meeting with elapsed time
- Context restore re-opens Slack to the channel you were in before entering focus mode
- Slack notifications are intercepted and routed through the Triage Dashboard during focus sessions

---

## Project Structure

```
deepworkai/
├── start.py                          # Main launcher — starts all components
├── requirements.txt                  # Python dependencies
├── .env                              # Your local config (not committed)
├── .env.example                      # Template — copy this to .env
├── data/
│   ├── activity.db                   # App-switch and git context events
│   ├── capsules.db                   # Workspace snapshots
│   ├── notifications.db              # Notification holding tank
│   ├── queue.db                      # Interruption queue
│   ├── next_step.txt                 # Current micro-journal note
│   ├── palette.json                  # Terminal command palette config
│   ├── context_anchor.json           # Saved cursor position
│   └── radar_state.json              # Last known CI/PR state
├── deepworkai/
│   ├── activity/
│   │   └── recorder.py               # Background activity event recorder
│   ├── service/
│   │   ├── deepwork_service.py       # Core TCP socket server
│   │   ├── deep_restore_core.py      # Workspace snapshot + restore engine
│   │   ├── slack_integration.py      # Slack DND + context capsule management
│   │   ├── lcd_state.py              # LCD display state synchronisation
│   │   ├── proc_utils.py             # Hidden subprocess helpers
│   │   └── paths.py                  # Centralised path constants
│   ├── features/
│   │   ├── focus_mode.py             # Focus session start/stop/toggle
│   │   ├── focus_timer.py            # Elapsed focus time → LCD
│   │   ├── cognitive_rewind.py       # Context summary builder
│   │   ├── triage_dashboard.py       # Notification review GUI (tkinter)
│   │   ├── notification_classifier.py# AI priority engine (rules + sklearn)
│   │   ├── notification_interceptor.py# Notification capture + routing
│   │   ├── meeting_mode.py           # Meeting in/out orchestrator
│   │   ├── micro_journal.py          # Next-step note capture
│   │   ├── _journal_overlay.py       # PyQt6 overlay subprocess
│   │   ├── context_anchor.py         # File:line save + restore
│   │   ├── smart_queue.py            # Interruption queue
│   │   ├── blocker_radar.py          # GitHub CI/PR poller
│   │   ├── git_pulse.py              # Branch push haptic detector
│   │   ├── terminal_palette.py       # 6-slot terminal command launcher
│   │   ├── workspace_restore.py      # Thin feature wrapper over core
│   │   └── debug_surface.py          # Debug shortcut injection
│   └── plugin/
│       ├── index.js                  # Plugin entry point
│       ├── src/
│       │   ├── tcp-client.js         # TCP connection to Python service
│       │   ├── adjustment-actions.js # Dial/button action handlers
│       │   └── test-actions.js       # Plugin test utilities
│       ├── package.json              # Node.js package manifest
│       └── esbuild.config.js         # Plugin build configuration
└── debug.log                         # Runtime debug output
```

---

## Troubleshooting

### Service won't start

- Check `data/service.log` for Python errors
- Make sure port `57321` is not occupied: `netstat -an | findstr 57321`
- Confirm Python 3.10+ is on your PATH: `python --version`

### Plugin not showing in Logitech Options+

- Confirm Developer Mode is enabled in Options+ → Settings
- Re-run `npm run link` from inside `deepworkai/plugin/`
- Restart Logitech Options+ after linking

### Focus Shield not setting Slack DND

- Confirm `SLACK_TOKEN` is set in `.env` and starts with `xoxb-` or `xoxp-`
- Verify the token has `dnd:write` scope in your Slack app settings
- Check `data/service.log` for Slack API error messages

### Blocker Radar shows "unknown"

- Confirm `GITHUB_TOKEN` and `GITHUB_REPO` are set in `.env`
- Test your token manually: `curl -H "Authorization: token YOUR_TOKEN" https://api.github.com/user`
- Make sure your token has `repo` and `notifications` scopes

### Workspace restore opens wrong windows

- Restore works best when the same applications are installed and on the same paths as when the snapshot was taken
- Check `data/capsules.db` — snapshots older than the apps being updated may have stale paths

### Notification classifier crashing

- Run `pip install scikit-learn` if you skipped optional dependencies
- The system falls back to rules-only classification if sklearn is unavailable — check `data/service.log` for the fallback warning

### Terminal Palette not opening

- Ensure `wt.exe` (Windows Terminal) is installed. Install it from the Microsoft Store.
- Without it, commands fall back to a plain PowerShell window. Edit `data/palette.json` to verify your commands are correct.

---

> **Logs are your friend.** All activity is written to `data/service.log` and `data/deepworkai.log`. When something isn't working, check there first.

---

*Built for deep work. Stay in the zone.*