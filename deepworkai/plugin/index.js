/**
 * Deep Work AI — Logitech Plugin Entry Point (v2)
 * =================================================
 * 8 button actions + 1 dial = perfect for the MX Creative Console 3×3 keypad.
 *
 * Suggested button layout:
 *  [Capture]   [Restore]   [Focus Shield]
 *  [Meeting]   [Triage]    [Journal]
 *  [Queue]     [Rewind]    [---unused---]
 *  [←  Time Travel dial  →] [press = restore snapshot]
 */

import { PluginSDK } from '@logitech/plugin-sdk';

import {
  CaptureAction,
  RestoreAction,
  FocusShieldAction,
  MeetingModeAction,
  TriageAction,
  JournalCaptureAction,
  QueueAction,
  CognitiveRewindAction,
} from './src/test-actions.js';

import { TimeTravelAction } from './src/adjustment-actions.js';
import { log, ensureService } from './src/tcp-client.js';

const pluginSDK = new PluginSDK();

// ── Register 8 button actions + 1 dial ────────────────────────────────────────
const ACTIONS = [
  new CaptureAction(),        // Button 1
  new RestoreAction(),        // Button 2
  new FocusShieldAction(),    // Button 3
  new MeetingModeAction(),    // Button 4
  new TriageAction(),         // Button 5
  new JournalCaptureAction(), // Button 6
  new QueueAction(),          // Button 7
  new CognitiveRewindAction(),// Button 8
  new TimeTravelAction(),     // Dial
];

for (const action of ACTIONS) {
  pluginSDK.registerAction(action);
}

log(`[PLUGIN] Deep Work AI v3.2.0 — ${ACTIONS.length} actions (8 buttons + dial)`);

await pluginSDK.connect();

log('[PLUGIN] Connected to Logitech Options+ — all systems ready');

// ── Auto-start Python backend ──────────────────────────────────────────────────
ensureService().then(ok => {
  log(ok
    ? '[PLUGIN] Backend service running'
    : '[PLUGIN] WARNING: Backend did not start — will retry on first button press'
  );
});

// ── LCD Polling (5-second refresh) ─────────────────────────────────────────────
// Uses esbuild-injected require() — do NOT import createRequire (already declared by esmShimPlugin)
const _fs   = require('fs');
const _path = require('path');

const LCD_STATE_PATH = _path.resolve(
  _path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Z]:)/, '$1')),
  '..', '..', 'data', 'lcd_state.json'
);

function getLcdLabels(state) {
  const mode = state.mode || 'ready';
  if (mode === 'meeting') {
    const mins = state.focus_mins || 0;
    return [`📅 ${mins}m`, 'End Mtg', '', '', '', '', '', '', ''];
  }
  const ci    = state.ci === 'pass' ? '✅ CI' : state.ci === 'fail' ? '❌ CI' : 'CI...';
  const prs   = state.prs > 0 ? `PRs:${state.prs}` : 'No PRs';
  const timer = state.focus_mins > 0 ? `⏱${state.focus_mins}m` : 'Focus';
  const queue = state.queue > 0 ? `Q:${state.queue}` : 'Queue';
  return [ci, prs, timer, queue, '', '', '', '', ''];
}

function updateLcd() {
  try {
    if (!_fs.existsSync(LCD_STATE_PATH)) return;
    const state  = JSON.parse(_fs.readFileSync(LCD_STATE_PATH, 'utf8'));
    const labels = getLcdLabels(state);
    if (pluginSDK.setButtonLabel) {
      labels.forEach((lbl, i) => { if (lbl) pluginSDK.setButtonLabel(i, lbl); });
    }
  } catch (_) {}
}

setInterval(updateLcd, 5000);
updateLcd();
