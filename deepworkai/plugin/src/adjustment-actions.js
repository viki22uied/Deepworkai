/**
 * Deep Work AI — Time Travel Dial
 * ================================
 * Rotate to select how many minutes back to go.
 * Stop rotating → auto-restores after 1 second of inactivity.
 *
 * Why auto-fire? The Logitech SDK v0.1.1 AdjustmentAction does not
 * expose dial-press events through execute(). The "rotate and pause"
 * UX is better anyway — no separate press needed.
 *
 * ← rotate left  = go further back in time  (more minutes)
 * → rotate right = come forward in time     (fewer minutes)
 * Stop turning   = auto-restores after 1 second
 */

import { AdjustmentAction } from '@logitech/plugin-sdk';
import { ensureService, sendCommand, log } from './tcp-client.js';

let _rewindMinutes = 15;      // currently selected target
let _fireTimer     = null;    // auto-fire debounce timer
let _lastFireMs    = 0;       // prevent duplicate fires

const MIN_MINUTES  = 5;
const MAX_MINUTES  = 480;     // 8 hours max
const AUTO_FIRE_MS = 1000;    // fire 1s after last rotation tick
const COOLDOWN_MS  = 3000;    // don't fire again within 3s of last restore


function scheduleRewind() {
  // Clear any pending fire
  if (_fireTimer) {
    clearTimeout(_fireTimer);
    _fireTimer = null;
  }

  _fireTimer = setTimeout(async () => {
    _fireTimer = null;

    // Cooldown check
    const now = Date.now();
    if (now - _lastFireMs < COOLDOWN_MS) {
      log(`[DIAL] Cooldown — skipping fire (${_rewindMinutes}m)`);
      return;
    }
    _lastFireMs = now;

    log(`[DIAL] Auto-fire → REWIND:${_rewindMinutes}`);
    await ensureService();
    try {
      const result = await sendCommand(`REWIND:${_rewindMinutes}`);
      log(`[DIAL] Result: ${result}`);
    } catch (e) {
      log(`[DIAL] REWIND failed: ${e.message}`);
    }
  }, AUTO_FIRE_MS);
}


export class TimeTravelAction extends AdjustmentAction {
  name        = 'time_travel';
  displayName = 'Time Travel';
  description = 'Rotate ← further back · → closer · Stop = auto-restore';
  groupName   = 'Deep Work AI';

  /**
   * Called by SDK on every encoder tick.
   * tick > 0 = clockwise (forward in time = fewer minutes)
   * tick < 0 = counter-clockwise (further back = more minutes)
   */
  async execute(event) {
    const tick = event?.tick ?? 0;

    if (tick === 0) {
      // Some SDK versions call execute(tick=0) for press — treat same as pause
      scheduleRewind();
      return;
    }

    // Each tick = ±5 minutes
    // Counter-clockwise (tick < 0) = go further BACK = increase minutes
    // Clockwise        (tick > 0) = come FORWARD    = decrease minutes
    const delta = -Math.sign(tick) * 5;
    _rewindMinutes = Math.max(MIN_MINUTES, Math.min(MAX_MINUTES, _rewindMinutes + delta));

    log(`[DIAL] Selected: ${_rewindMinutes}m ago (tick=${tick})`);
    scheduleRewind();
  }
}
