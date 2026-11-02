/**
 * Deep Work AI — Logitech Plugin Entry Point
 * ==========================================
 * The Rule of Three: three keys + one dial.
 *
 *   [ Focus ]  [ Resume ]  [ Inbox ]      ( Time Travel dial )
 *
 * Each key does several jobs via 1/2/3 presses — see src/test-actions.js.
 */

import { PluginSDK } from '@logitech/plugin-sdk';

import { FocusKey, ResumeKey, InboxKey } from './src/test-actions.js';
import { TimeTravelAction } from './src/adjustment-actions.js';
import { log, ensureService, getProjectRoot, bundledAppExe } from './src/tcp-client.js';

const pluginSDK = new PluginSDK();

// ── Register 3 keys + 1 dial ──────────────────────────────────────────────────
const ACTIONS = [
  new FocusKey(),
  new ResumeKey(),
  new InboxKey(),
  new TimeTravelAction(),     // Dial
];

for (const action of ACTIONS) {
  pluginSDK.registerAction(action);
}

log(`[PLUGIN] Deep Work AI v4.0.0 — ${ACTIONS.length} actions (3 keys + dial)`);

await pluginSDK.connect();

log('[PLUGIN] Connected to Logitech Options+ — all systems ready');
log(bundledAppExe() ? '[PLUGIN] Using bundled Deep Work AI app'
                    : `[PLUGIN] Development mode, project root: ${getProjectRoot() ?? 'NOT FOUND'}`);

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
