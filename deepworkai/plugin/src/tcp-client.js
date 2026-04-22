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
const COMMAND_TIMEOUT = 8000;
const MAX_RETRIES = 3;
const RETRY_DELAY = 500;
const SPAWN_WAIT = 3500;

let _serviceSpawning = false;

// ── Logging ──────────────────────────────────────────────────────────────────
const LOG_FILE = path.resolve(__dirname, '..', 'debug.log');

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
function getConfig() {
  const configFile = path.resolve(__dirname, '..', 'config.json');
  try {
    if (fs.existsSync(configFile)) {
      return JSON.parse(fs.readFileSync(configFile, 'utf-8'));
    }
  } catch (_) {}
  return {};
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
  return path.resolve(__dirname, '..', 'service', 'deepwork_service.py');
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

    if (!fs.existsSync(servicePath)) {
      log(`[SPAWN] ERROR: Service not found at ${servicePath}`);
      _serviceSpawning = false;
      resolve(false);
      return;
    }

    log(`[SPAWN] Starting: ${pythonPath} ${servicePath}`);
    try {
      const child = spawn(pythonPath, [servicePath], {
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

export async function ensureService() {
  const alive = await isServiceAlive();
  if (alive) return true;
  log('[SERVICE] Not running — spawning...');
  return spawnService();
}

// ── Send Command (with retry) ────────────────────────────────────────────────
function sendCommandOnce(command) {
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

    client.setTimeout(COMMAND_TIMEOUT);
    client.connect(PORT, HOST, () => { client.write(command + '\n'); });
    client.on('data', (data) => {
      output += data.toString();
      if (output.includes('\n')) settle(null, output.trim());
    });
    client.on('error', (err) => settle(err));
    client.on('timeout', () => settle(new Error('Command timeout')));
  });
}

export async function sendCommand(command) {
  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const result = await sendCommandOnce(command);
      log(`[CMD] ${command} → ${result}`);
      return result;
    } catch (e) {
      log(`[CMD] Attempt ${attempt}/${MAX_RETRIES} failed: ${e.message}`);
      if (attempt < MAX_RETRIES) {
        await ensureService();
        await new Promise((r) => setTimeout(r, RETRY_DELAY * attempt));
      }
    }
  }
  throw new Error(`Command ${command} failed after ${MAX_RETRIES} attempts`);
}
