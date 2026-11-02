# Changelog

## 4.0.0 — November 2026

The first version was built for the Logitech DevStudio Hackathon (April 2026).
Placements, final-year exams and an internship kept the project on hold after that;
this release is the rebuild that followed.

### Controls
- Three multi-press keys (Focus, Resume, Inbox) and the dial replace eight buttons
- The dial is Time Travel, and steps the debugger during a debug session
- Button presses no longer time out; commands are never sent twice

### Workflow intelligence (fully local)
- Detects what you are doing and a 0–100 focus score
- Saves your context automatically when you are interrupted
- Holds, batches or lets notifications through depending on your focus
- Dependency-free classifier (replaces scikit-learn, ~130 MB less memory)

### Time Travel
- Timeline of saved moments showing what you were doing in each
- Snapshots every 10 minutes while working

### Hub
- One window for Focus, Time Travel, Inbox and Insights
- Bento design, light and dark themes, sharp on high-DPI screens
- Opens instantly; frees its memory after 20 minutes hidden

### Fixes
- Restore no longer reopens old, closed browser tabs
- Snapshots, project detection and the context anchor now use real data
- Several crashes and data-path bugs

### Security and privacy
- Local authentication on the service port, connection limits
- Encrypted token storage (Windows DPAPI)
- No private content in logs; secrets stripped from saved URLs
- Command-injection and unsafe-URL fixes; personal data removed from the repo

## 3.2.0 — April 2026
- Hackathon release
