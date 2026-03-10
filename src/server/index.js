'use strict';

const path = require('path');
const fs = require('fs');
const http = require('http');
const express = require('express');
const rateLimit = require('express-rate-limit');
const { WebSocketServer } = require('ws');
const MidiHandler = require('./midiHandler');
const TwitchBot = require('./twitchBot');

// ─── Load config ──────────────────────────────────────────────────────────────
const configPath = path.resolve(__dirname, '../../config.json');
let config = { port: 3000, midiDevice: '', theme: 'default', noteSpeed: 4, twitch: { channel: '', oauth: '' } };
if (fs.existsSync(configPath)) {
  try {
    config = { ...config, ...JSON.parse(fs.readFileSync(configPath, 'utf8')) };
  } catch (e) {
    console.error('[Config] Failed to parse config.json:', e.message);
  }
} else {
  console.warn('[Config] config.json not found – using defaults. Copy config.example.json to get started.');
}

// ─── Express / HTTP server ────────────────────────────────────────────────────
const app = express();
const server = http.createServer(app);

// Basic rate-limiting for HTTP routes
const limiter = rateLimit({ windowMs: 60 * 1000, max: 120 });
app.use(limiter);

// Serve the client files
app.use(express.static(path.join(__dirname, '../client')));

// Inject runtime config into the page
app.get('/', (_req, res) => {
  const html = fs.readFileSync(path.join(__dirname, '../client/index.html'), 'utf8');
  const injected = html.replace(
    '<script src="visualizer.js"></script>',
    `<script>window.__CONFIG__ = ${JSON.stringify({
      theme: config.theme,
      noteSpeed: config.noteSpeed,
      wsUrl: `ws://\${location.host}`,
    })};</script>\n  <script src="visualizer.js"></script>`,
  );
  res.send(injected);
});

// ─── WebSocket server ─────────────────────────────────────────────────────────
const wss = new WebSocketServer({ server });
const clients = new Set();

wss.on('connection', (ws) => {
  clients.add(ws);
  console.log(`[WS] Client connected (${clients.size} total)`);
  ws.on('close', () => {
    clients.delete(ws);
    console.log(`[WS] Client disconnected (${clients.size} remaining)`);
  });
});

function broadcast(message) {
  const data = JSON.stringify(message);
  for (const ws of clients) {
    if (ws.readyState === ws.OPEN) ws.send(data);
  }
}

// ─── MIDI handler ─────────────────────────────────────────────────────────────
const midi = new MidiHandler(config.midiDevice);
midi.listPorts();
midi.open();

midi.on('noteOn',  (note, velocity) => broadcast({ type: 'noteOn',  note, velocity }));
midi.on('noteOff', (note)           => broadcast({ type: 'noteOff', note }));

// ─── Twitch bot ───────────────────────────────────────────────────────────────
const twitch = new TwitchBot(config.twitch || {}, (command, args) => {
  switch (command) {
    case 'theme':
      if (args[0]) {
        config.theme = args[0];
        broadcast({ type: 'config', data: { theme: config.theme } });
        console.log(`[Twitch] Theme changed to: ${config.theme}`);
      }
      break;
    case 'speed':
      if (args[0] && !isNaN(Number(args[0]))) {
        config.noteSpeed = Number(args[0]);
        broadcast({ type: 'config', data: { noteSpeed: config.noteSpeed } });
        console.log(`[Twitch] Note speed changed to: ${config.noteSpeed}`);
      }
      break;
    default:
      console.log(`[Twitch] Unknown command: ${command}`);
  }
});
twitch.connect();

// ─── Start ────────────────────────────────────────────────────────────────────
server.listen(config.port, () => {
  console.log(`[Server] Piano MIDI Visualizer running at http://localhost:${config.port}`);
});

// ─── Graceful shutdown ────────────────────────────────────────────────────────
process.on('SIGINT', () => {
  console.log('\n[Server] Shutting down…');
  midi.close();
  twitch.disconnect();
  server.close(() => process.exit(0));
});
