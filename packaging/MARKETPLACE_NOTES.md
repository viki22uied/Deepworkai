# Notes for the Logitech Marketplace review

Deep Work AI 4.0.0 (Beta) — `DeepWorkAi_4_0.lplug4`

## Summary

Deep Work AI is a focus plugin for the MX Creative Console. Three keys (Focus, Resume, Inbox)
and the dial (Time Travel) control all functions.

## Platform

- Windows 10 and Windows 11 only.
- Supported device: MX Creative Console (`LoupedeckExtendedFamily`).
- The plugin is labelled **Beta**.

## The bundled app

- The package contains the Deep Work AI app in `assets/app/DeepWorkAI/`.
  The app is Python, built with PyInstaller. Users do not need to install Python.
- The plugin starts `DeepWorkAI.exe` when a key is pushed for the first time.
  The app runs in the background without a console window.
- The app accepts connections only from `127.0.0.1`. Each command needs a random session key.
- Only one copy of the app can run at a time.
- The package is about 72 MB because of the bundled app and its Qt window.

## Antivirus

`DeepWorkAI.exe` is not code-signed yet. Some antivirus products and Windows SmartScreen can
show a warning for unsigned PyInstaller apps. The full source is public:
https://github.com/viki22uied/Deepworkai

## Data and network

- All data stays on the user's computer in `%LOCALAPPDATA%\DeepWorkAI\data`.
- No telemetry, no accounts, no developer server.
- Network access occurs only if the user connects GitHub, Slack or Jira with their own tokens.
  Tokens are encrypted with Windows DPAPI.

## Documents

- License: MIT — https://github.com/viki22uied/Deepworkai/blob/main/LICENSE
- End User License Agreement — https://github.com/viki22uied/Deepworkai/blob/main/EULA.md
- Privacy policy — https://github.com/viki22uied/Deepworkai/blob/main/PRIVACY.md
- Security — https://github.com/viki22uied/Deepworkai/blob/main/SECURITY.md

## How to test

1. Install the package. Put **Focus**, **Resume** and **Inbox** on keys, and **Time Travel** on the dial.
2. Push **Focus** 3 times. The message "Spot saved" shows.
3. Close a browser window. Push **Resume** 1 time. The browser opens again with its tabs.
4. Push **Inbox** 1 time. The Hub window opens.
5. Turn the dial left. Time Travel shows the saved moments. Push the dial to restore one.

## Known limitations (Beta)

- Brave locks its tab file while it runs. Brave tab restore is less exact than Chrome or Edge.
- The plugin cannot close browser tabs.

## Credits

Built by the Deep Work AI team: a Top 50 project and semi-finalist in the Logitech DevStudio Hackathon.
Contact: https://github.com/viki22uied/Deepworkai/issues
