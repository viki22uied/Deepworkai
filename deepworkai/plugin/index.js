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
import { log, ensureService, getProjectRoot } from './src/tcp-client.js';

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
log(`[PLUGIN] Project root: ${getProjectRoot() ?? 'NOT FOUND — set project_root in config.json'}`);

// ── Auto-start Python backend ──────────────────────────────────────────────────
ensureService().then(ok => {
  log(ok
    ? '[PLUGIN] Backend service running'
    : '[PLUGIN] WARNING: Backend did not start — will retry on first button press'
  );
});

// ── LCD labels ────────────────────────────────────────────────────────────────
// The previous LCD polling called pluginSDK.setButtonLabel(), which does not exist
// in @logitech/plugin-sdk 0.1.1 (it only offers registerAction/connect), and it
// read data/ from the wrong folder. It was a silent no-op, so it has been removed.
// The service still writes <repo>/data/lcd_state.json for when the SDK gains
// a label/image API.
