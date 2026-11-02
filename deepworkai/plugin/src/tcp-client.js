/**
 * Deep Work AI — TCP Command Client
 * Sends commands to the deepwork_service.py TCP server.
 */

import net from 'net';
import { spawn, spawnSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const HOST = '127.0.0.1';
const PORT = 57321;
const COMMAND_TIMEOUT = 30000;   // some service commands (CAPTURE/RESTORE) are slow
const MAX_RETRIES = 3;
const RETRY_DELAY = 500;
const SPAWN_WAIT = 3500;

let _serviceSpawning = false;

// ── Logging ──────────────────────────────────────────────────────────────────
const LOG_FILE = path.resolve(__dirname, '..', 'debug.log');

// Only command names and OK/ERROR outcomes are logged — results can contain
// notes, file names or tab URLs, which must never land in a plain-text log.
export function summarize(result) {
  const s = String(result ?? '');
  return s.split(' ').slice(0, 2).join(' ');
}

export function log(msg) {
  const ts = new Date().toISOString();
  const line = `[${ts}] ${msg}\n`;
  try {
    try {
      const stat = fs.statSync(LOG_FILE);
      if (stat.size > 512000) {
        const content = fs.readFileSync(LOG_FILE, 'utf-8');
        fs.writeFileSync(LOG_FILE, content.slice(-256000));
      }
    } catch (_) {}
    fs.appendFileSync(LOG_FILE, line);
  } catch (_) {}
}

// ── Python / Service Discovery ───────────────────────────────────────────────
// NOTE: after bundling, __dirname is the plugin's dist/ folder, and when the
// plugin is installed via `logitoolkit pack` it lives inside the Logi plugin
// directory, far from the repo. So never assume a fixed relative layout —
// search a few candidate locations instead.
function userConfigDir() {
  // Per-user settings live outside the plugin folder, which Options+ replaces on every update.
  if (process.platform === 'win32' && process.env.APPDATA) return path.join(process.env.APPDATA, 'DeepWorkAI');
  return path.join(process.env.HOME || '', '.config', 'deepworkai');
}

function getConfig() {
  const candidates = [
    path.join(userConfigDir(), 'config.json'),                     // per-user (marketplace installs)
    path.resolve(__dirname, '..', 'config.json'),                  // plugin/config.json (development)
  ];
  for (const configFile of candidates) {
    try {
      if (fs.existsSync(configFile)) {
        return JSON.parse(fs.readFileSync(configFile, 'utf-8'));
      }
    } catch (e) {
      log(`[CONFIG] Failed to parse ${configFile}: ${e.message}`);
    }
  }
  return {};
}

const SERVICE_REL = path.join('deepworkai', 'service', 'deepwork_service.py');

/** Repo root (folder containing deepworkai/service/deepwork_service.py). */
export function getProjectRoot() {
  const cfg = getConfig();
  if (process.env.DEEPWORKAI_ROOT && fs.existsSync(path.join(process.env.DEEPWORKAI_ROOT, SERVICE_REL))) {
    return process.env.DEEPWORKAI_ROOT;
  }
  if (cfg.project_root && fs.existsSync(path.join(cfg.project_root, SERVICE_REL))) {
    return cfg.project_root;
  }
  if (cfg.service_script && fs.existsSync(cfg.service_script)) {
    return path.resolve(path.dirname(cfg.service_script), '..', '..');
  }
  // Standard per-user install location of the Deep Work AI app.
  const standard = process.platform === 'win32' && process.env.LOCALAPPDATA
    ? path.join(process.env.LOCALAPPDATA, 'DeepWorkAI') : null;
  if (standard && fs.existsSync(path.join(standard, SERVICE_REL))) return standard;
  // Walk up from the bundle location (works when the plugin is linked from the repo).
  let dir = __dirname;
  for (let i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(dir, SERVICE_REL))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function getPythonExecutable() {
  const cfg = getConfig();
  if (cfg.pythonpath && fs.existsSync(cfg.pythonpath)) return cfg.pythonpath;

  for (const candidate of ['pythonw', 'python', 'python3']) {
    try {
      const r = spawnSync('where', [candidate], { encoding: 'utf-8' });
      if (r.status === 0 && r.stdout.trim()) {
        const found = r.stdout.trim().split('\n')[0].trim();
        if (fs.existsSync(found)) return found;
      }
    } catch (_) {}
  }
  return 'pythonw';
}

function getServicePath() {
  const cfg = getConfig();
  if (cfg.service_script && fs.existsSync(cfg.service_script)) return cfg.service_script;
  const root = getProjectRoot();
  return root ? path.join(root, SERVICE_REL) : null;
}

// ── Service Health ───────────────────────────────────────────────────────────
export function isServiceAlive() {
  return new Promise((resolve) => {
    const sock = new net.Socket();
    sock.setTimeout(2000);
    sock.connect(PORT, HOST, () => { sock.write('PING\n'); });
    sock.on('data', (data) => {
      sock.destroy();
      resolve(data.toString().trim().includes('PONG'));
    });
    sock.on('error', () => { sock.destroy(); resolve(false); });
    sock.on('timeout', () => { sock.destroy(); resolve(false); });
  });
}

function spawnService() {
  return new Promise((resolve) => {
    if (_serviceSpawning) {
      setTimeout(() => resolve(true), SPAWN_WAIT);
      return;
    }
    _serviceSpawning = true;

    const pythonPath = getPythonExecutable();
    const servicePath = getServicePath();

    if (!servicePath || !fs.existsSync(servicePath)) {
      log(`[SPAWN] ERROR: Service not found (${servicePath}). Install the Deep Work AI app, or set project_root in %APPDATA%\\DeepWorkAI\\config.json.`);
      _serviceSpawning = false;
      resolve(false);
      return;
    }

    log(`[SPAWN] Starting: ${pythonPath} ${servicePath}`);
    try {
      const child = spawn(pythonPath, [servicePath], {
        cwd: path.dirname(servicePath),
        detached: true,
        stdio: 'ignore',
        windowsHide: true,
      });
      child.on('error', (err) => log(`[SPAWN] Error: ${err.message}`));
      child.unref();

      setTimeout(async () => {
        _serviceSpawning = false;
        const alive = await isServiceAlive();
        log(`[SPAWN] Service ${alive ? 'started' : 'not responding yet'}`);
        resolve(alive);
      }, SPAWN_WAIT);
    } catch (e) {
      log(`[SPAWN] Exception: ${e.message}`);
      _serviceSpawning = false;
      resolve(false);
    }
  });
}

let _lastOk = 0;
const ALIVE_TTL = 15000;

export async function ensureService() {
  if (Date.now() - _lastOk < ALIVE_TTL) return true;   // skip a round trip on rapid presses
  const alive = await isServiceAlive();
  if (alive) _lastOk = Date.now();
  if (alive) return true;
  log('[SERVICE] Not running — spawning...');
  return spawnService();
}

// ── Session key ──────────────────────────────────────────────────────────────
// The service writes a fresh random key to <repo>/data/.session_key on start;
// every command except PING must be prefixed with "@<key> ".
function readSessionKey() {
  const root = getProjectRoot();
  if (!root) return '';
  try {
    return fs.readFileSync(path.join(root, 'data', '.session_key'), 'utf-8').trim();
  } catch (_) {
    return '';
  }
}

// ── Send Command (with retry) ────────────────────────────────────────────────
function sendCommandOnce(command) {
  const wire = command === 'PING' ? command : `@${readSessionKey()} ${command}`;
  return new Promise((resolve, reject) => {
    const client = new net.Socket();
    let output = '';
    let settled = false;

    const settle = (err, result) => {
      if (settled) return;
      settled = true;
      client.destroy();
      if (err) reject(err);
      else resolve(result);
    };

    let sent = false;
    client.setTimeout(COMMAND_TIMEOUT);
    client.connect(PORT, HOST, () => { sent = true; client.write(wire + '\n'); });
    client.on('data', (data) => {
      output += data.toString();
      if (output.includes('\n')) settle(null, output.trim());
    });
    client.on('error', (err) => { err.sent = sent; settle(err); });
    client.on('timeout', () => { const e = new Error('Command timeout'); e.sent = sent; settle(e); });
    client.on('end', () => settle(null, output.trim()));
  });
}

export async function sendCommand(command) {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const result = await sendCommandOnce(command);
      _lastOk = Date.now();
      if (result.startsWith('ERROR AUTH')) {
        log('[CMD] Rejected: session key missing or stale — is the Deep Work AI app installed and running?');
      }
      log(`[CMD] ${command.split(':')[0]} → ${summarize(result)}`);
      return result;
    } catch (e) {
      log(`[CMD] Attempt ${attempt}/${MAX_RETRIES} failed: ${e.message}`);
      // If the command already reached the service, do NOT resend it:
      // toggles (SHIELD_TOGGLE, MEETING_TOGGLE) would flip back, CAPTURE would duplicate.
      if (e.sent) throw e;
      if (attempt < MAX_RETRIES) {
        await ensureService();
        await new Promise((r) => setTimeout(r, RETRY_DELAY * attempt));
      }
    }
  }
  throw new Error(`Command ${command} failed after ${MAX_RETRIES} attempts`);
}
