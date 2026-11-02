/**
 * Deep Work AI — The Rule of Three
 * =================================
 * Three keys, each doing the work of several, plus the Time Travel dial.
 * Multi-press is detected here: presses within PRESS_WINDOW_MS are counted,
 * then the matching command is sent once.
 *
 *   FOCUS   1× Focus Shield on/off (auto-saves workspace first)
 *           2× Meeting mode on/off
 *           3× Save my spot (workspace snapshot + exact file:line anchor)
 *   RESUME  1× Restore workspace, jump to anchored line, show "where was I"
 *           2× Write a next-step note
 *   INBOX   1× Open the Hub (Inbox if items are waiting, otherwise Focus)
 *           2× Queue this interruption for later
 *           3× Release everything that was held
 *   DIAL    rotate = travel back in time; during a debug session it steps
 *           the debugger instead (see adjustment-actions.js)
 *
 * Capture has no key: the local AI saves context automatically.
 */

import { CommandAction } from '@logitech/plugin-sdk';
import { ensureService, sendCommand, log } from './tcp-client.js';

const PRESS_WINDOW_MS = 350;

function run(name, cmd) {
  (async () => {
    try {
      await ensureService();
      const r = await sendCommand(cmd);
      log(`[ACTION] ${name} → ${r}`);
    } catch (e) {
      log(`[ACTION] ${name} FAILED: ${e.message}`);
    }
  })();
}

/** Counts rapid presses, then fires the command for that count (falls back to the highest defined). */
class MultiPressAction extends CommandAction {
  commands = {};          // { 1: [label, CMD], 2: [...], 3: [...] }
  _count = 0;
  _timer = null;

  onKeyDown() {           // returns immediately so Options+ never times out
    this._count += 1;
    clearTimeout(this._timer);
    const max = Math.max(...Object.keys(this.commands).map(Number));
    const fire = () => {
      const n = Math.min(this._count, max);
      this._count = 0;
      const [label, cmd] = this.commands[n];
      log(`[KEY] ${this.displayName} ×${n} → ${label}`);
      run(`${this.displayName}:${label}`, cmd);
    };
    if (this._count >= max) fire();                       // no need to wait
    else this._timer = setTimeout(fire, PRESS_WINDOW_MS);
  }
}

export class FocusKey extends MultiPressAction {
  name        = 'dw_focus';
  displayName = 'Focus';
  description = '1× Focus Shield · 2× Meeting mode · 3× Save my spot';
  groupName   = 'Deep Work AI';
  commands    = { 1: ['shield', 'SHIELD_TOGGLE'], 2: ['meeting', 'MEETING_TOGGLE'],
                  3: ['save-spot', 'SAVE_SPOT'] };
}

export class ResumeKey extends MultiPressAction {
  name        = 'dw_resume';
  displayName = 'Resume';
  description = '1× Restore workspace + where was I · 2× Next-step note';
  groupName   = 'Deep Work AI';
  commands    = { 1: ['resume', 'RESUME'], 2: ['journal', 'JOURNAL_CAPTURE'] };
}

export class InboxKey extends MultiPressAction {
  name        = 'dw_inbox';
  displayName = 'Inbox';
  description = '1× Open Hub · 2× Queue interruption · 3× Release held items';
  groupName   = 'Deep Work AI';
  commands    = { 1: ['hub', 'HUB'], 2: ['queue', 'QUEUE_ADD'], 3: ['release', 'RELEASE_HELD'] };
}
