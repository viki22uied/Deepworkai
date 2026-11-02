/**
 * Deep Work AI — Button Actions (v2 trimmed for 3×3 keypad)
 * ===========================================================
 * Exactly 8 button actions + 1 dial = perfect fit for MX Creative Console.
 *
 * Layout suggestion:
 *  [Capture]   [Restore]   [Focus Shield]
 *  [Meeting]   [Triage]    [Journal]
 *  [Queue]     [Context]   [---empty---]
 *  [←dial→]   [press=restore snapshot]
 */

import { CommandAction } from '@logitech/plugin-sdk';
import { ensureService, sendCommand, log } from './tcp-client.js';

// Fire-and-forget: the SDK awaits onKeyDown() before replying to Logi Options+.
// Blocking here for service spawn (3.5s) + slow commands makes Options+ time the
// request out, so the button appears to do nothing. Return immediately instead.
function exec(name, cmd) {
  log(`[ACTION] ${name} pressed`);
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

// ── 1. Capture Workspace ──────────────────────────────────────────────────────
export class CaptureAction extends CommandAction {
  name        = 'capture_workspace';
  displayName = 'Capture Workspace';
  description = 'Snapshot all windows, tabs, git branch and cursor context';
  groupName   = 'Deep Work AI';
  onKeyDown() { exec('Capture', 'CAPTURE'); }
}

// ── 2. Restore Workspace ──────────────────────────────────────────────────────
export class RestoreAction extends CommandAction {
  name        = 'restore_workspace';
  displayName = 'Restore Workspace';
  description = 'Restore the last captured workspace snapshot';
  groupName   = 'Deep Work AI';
  onKeyDown() { exec('Restore', 'RESTORE'); }
}

// ── 3. Focus Shield ───────────────────────────────────────────────────────────
export class FocusShieldAction extends CommandAction {
  name        = 'focus_shield';
  displayName = 'Focus Shield';
  description = 'Toggle deep focus: kills distractions, starts timer, holds notifications';
  groupName   = 'Deep Work AI';
  onKeyDown() { exec('Shield', 'SHIELD_TOGGLE'); }
}

// ── 4. Meeting Mode ───────────────────────────────────────────────────────────
export class MeetingModeAction extends CommandAction {
  name        = 'meeting_mode';
  displayName = 'Meeting Mode';
  description = 'Toggle: saves workspace + DND before meeting, restores after';
  groupName   = 'Deep Work AI';
  onKeyDown() { exec('Meeting', 'MEETING_TOGGLE'); }
}

// ── 5. Triage Dashboard ───────────────────────────────────────────────────────
export class TriageAction extends CommandAction {
  name        = 'triage_dashboard';
  displayName = 'Triage Dashboard';
  description = 'Open notification Holding Tank — HIGH/MEDIUM/LOW priority view';
  groupName   = 'Deep Work AI';
  onKeyDown() { exec('Triage', 'TRIAGE_SHOW'); }
}

// ── 6. Journal — Next Step ────────────────────────────────────────────────────
export class JournalCaptureAction extends CommandAction {
  name        = 'journal_capture';
  displayName = 'Journal — Next Step';
  description = 'Open micro-journal overlay — type one line, Enter saves, Esc cancels';
  groupName   = 'Deep Work AI';
  onKeyDown() { exec('Journal', 'JOURNAL_CAPTURE'); }
}

// ── 7. Queue Interruption ─────────────────────────────────────────────────────
export class QueueAction extends CommandAction {
  name        = 'queue_interruption';
  displayName = 'Queue Interruption';
  description = 'Log this interruption for later — live count shown on LCD';
  groupName   = 'Deep Work AI';
  onKeyDown() { exec('Queue', 'QUEUE_ADD'); }
}

// ── 8. Context Rewind ─────────────────────────────────────────────────────────
export class CognitiveRewindAction extends CommandAction {
  name        = 'cognitive_rewind';
  displayName = 'Context Rewind';
  description = 'See what you were doing: git branch, open files, last note';
  groupName   = 'Deep Work AI';
  onKeyDown() { exec('Rewind', 'COGNITIVE_REWIND'); }
}
