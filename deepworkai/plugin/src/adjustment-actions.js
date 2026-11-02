/**
 * Deep Work AI — Time Travel Dial
 * ================================
 * Turn the dial and a Time Travel overlay appears, showing your saved moments
 * with what you were doing at each one (activity, repo/branch, file, tabs,
 * focus score, your note).
 *
 *   ← counter-clockwise = further back in time
 *   → clockwise         = towards now ("Now" = cancel, nothing restored)
 *   stop turning        = the selected moment is restored after COMMIT_MS
 *
 * Context-aware: while a debug session is running the dial steps the debugger
 * instead (→ Step Over, ← Step Out). The service decides which mode applies.
 */

import { AdjustmentAction } from '@logitech/plugin-sdk';
import { sendCommand, log, summarize } from './tcp-client.js';

const COMMIT_MS = 2500;      // pause long enough to read the card, short enough to feel instant

let _commitTimer = null;
let _queue = Promise.resolve();   // keep ticks in order

function scheduleCommit() {
  clearTimeout(_commitTimer);
  _commitTimer = setTimeout(async () => {
    try {
      log(`[DIAL] ${summarize(await sendCommand('TRAVEL_COMMIT'))}`);
    } catch (e) {
      log(`[DIAL] commit failed: ${e.message}`);
    }
  }, COMMIT_MS);
}

export class TimeTravelAction extends AdjustmentAction {
  name        = 'time_travel';
  displayName = 'Time Travel';
  description = 'Turn ← to go back through your day · → towards now · stop to restore';
  groupName   = 'Deep Work AI';
  hasReset    = false;   // required by AdjustmentAction (abstract in the SDK)

  /** Called by the SDK on every encoder tick. Returns immediately. */
  execute(event) {
    const tick = Number.isFinite(event?.tick) ? event.tick : 0;
    if (tick === 0) return;
    _queue = _queue.then(() => this._route(tick));
  }

  async _route(tick) {
    try {
      const r = await sendCommand(`DIAL:${tick}`);
      log(`[DIAL] ${summarize(r)}`);
      if (r.includes('travel') && !r.includes('noop')) scheduleCommit();
      else clearTimeout(_commitTimer);          // debugger consumed it
    } catch (e) {
      log(`[DIAL] ${e.message}`);
    }
  }
}
