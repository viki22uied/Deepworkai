/**
 * Deep Work AI — Time Travel Dial
 * ================================
 * Turn the dial and a Time Travel overlay appears, showing your saved moments
 * with what you were doing at each one (open windows, tabs, focus score, your note).
 *
 *   ← counter-clockwise = further back in time
 *   → clockwise         = towards now ("Now" = nothing restored)
 *   press the dial      = restore the selected moment (Resume does the same)
 *   stop turning        = nothing happens; after IDLE_CLOSE_MS the overlay closes
 *
 * Stopping used to restore automatically, so a small accidental bump could reopen
 * and rearrange windows from an older moment. Restoring now always needs a press.
 *
 * Context-aware: while a debug session is running the dial steps the debugger
 * instead (→ Step Over, ← Step Out). The service decides which mode applies.
 */

import { AdjustmentAction, CommandAction } from '@logitech/plugin-sdk';
import { sendCommand, log, summarize } from './tcp-client.js';

const IDLE_CLOSE_MS = 30000;   // browsing left alone: close without restoring

let _idleTimer = null;
let _queue = Promise.resolve();   // keep ticks in order

function scheduleIdleClose() {
  clearTimeout(_idleTimer);
  _idleTimer = setTimeout(async () => {
    try {
      log(`[DIAL] ${summarize(await sendCommand('TRAVEL_CLOSE'))}`);
    } catch (e) {
      log(`[DIAL] close failed: ${e.message}`);
    }
  }, IDLE_CLOSE_MS);
}

async function commit() {
  clearTimeout(_idleTimer);
  await _queue;                                  // apply every tick before restoring
  try {
    log(`[DIAL] ${summarize(await sendCommand('TRAVEL_COMMIT'))}`);
  } catch (e) {
    log(`[DIAL] commit failed: ${e.message}`);
  }
}

export class TimeTravelAction extends AdjustmentAction {
  name        = 'time_travel';
  displayName = 'Time Travel';
  description = 'Turn ← to go back through your day · → towards now · press to restore';
  groupName   = 'Deep Work AI';
  hasReset    = true;    // the dial press: see TimeTravelRestore

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
      if (r.includes('travel') && !r.includes('noop')) scheduleIdleClose();
      else clearTimeout(_idleTimer);            // debugger consumed it
    } catch (e) {
      log(`[DIAL] ${e.message}`);
    }
  }
}

/** The dial's press (its reset command), also usable on a key: restore the selected moment. */
export class TimeTravelRestore extends CommandAction {
  name        = 'time_travel_RESET';
  displayName = 'Restore moment';
  description = 'Restore the moment selected with the Time Travel dial';
  groupName   = 'Deep Work AI';

  onKeyDown() {           // returns immediately so Options+ never times out
    commit();
  }
}
