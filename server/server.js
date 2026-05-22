'use strict';
const http = require('http');
const { WebSocketServer } = require('ws');
const { parseInbound, kikReply } = require('./adapters/kik');

// ── Config ────────────────────────────────────────────────────────────────────
const HTTP_PORT        = process.env.HTTP_PORT ? +process.env.HTTP_PORT : 8765;
const WS_PORT          = process.env.WS_PORT   ? +process.env.WS_PORT   : 8766;
const POLL_DURATION_MS = process.env.POLL_MS   ? +process.env.POLL_MS   : 30_000;
const COOLDOWN_MS      = process.env.COOL_MS   ? +process.env.COOL_MS   : 15_000;
const KIK_USERNAME     = process.env.KIK_USERNAME || '';
const KIK_API_KEY      = process.env.KIK_API_KEY  || '';

// ── Poll categories ───────────────────────────────────────────────────────────
const CATEGORIES = [
  {
    id: 'theme',
    label: 'Note Theme',
    options: ['Rainbow', 'Riders on the Storm', 'Moonlight Sonata', 'Light My Fire'],
    applyMsg(i) {
      return { type: 'apply_change', category: 'theme', theme_index: [1, 6, 7, 8][i] };
    },
  },
  {
    id: 'color',
    label: 'Trail Colour',
    options: ['Ocean Blue', 'Sunset Red', 'Forest Green', 'Neon Purple'],
    _cols: [[60,140,255],[255,80,60],[60,220,100],[180,60,255]],
    applyMsg(i) {
      const [r,g,b] = this._cols[i];
      return { type: 'apply_change', category: 'color', r, g, b };
    },
  },
  {
    id: 'speed',
    label: 'Trail Speed',
    options: ['Slow', 'Normal', 'Fast', 'Very Fast'],
    _speeds: [200, 400, 600, 900],
    applyMsg(i) {
      return { type: 'apply_change', category: 'speed', speed_px_per_sec: this._speeds[i] };
    },
  },
  {
    id: 'effects',
    label: 'Effects',
    options: ['Sparks On', 'Sparks Off', 'Smoke On', 'Smoke Off'],
    _fx: [
      { effect: 'sparks', enabled: true  },
      { effect: 'sparks', enabled: false },
      { effect: 'smoke',  enabled: true  },
      { effect: 'smoke',  enabled: false },
    ],
    applyMsg(i) {
      return { type: 'apply_change', category: 'effects', ...this._fx[i] };
    },
  },
];

// ── WebSocket server ──────────────────────────────────────────────────────────
const wss = new WebSocketServer({ port: WS_PORT });
const clients = { visualizer: new Set(), overlay: new Set() };

wss.on('connection', ws => {
  let role = null;
  ws.on('message', raw => {
    try {
      const msg = JSON.parse(raw);
      if (msg.type === 'identify' && msg.role) {
        role = msg.role;
        if (clients[role]) clients[role].add(ws);
        // Send current state to newly connected client
        if (state === 'active' && currentPoll) {
          const cat = currentPoll.cat;
          const elapsed = Date.now() - currentPoll.startTime;
          const remaining = Math.max(0, POLL_DURATION_MS - elapsed);
          send(ws, { type: 'poll_start', category: cat.id, label: cat.label, options: cat.options, duration_ms: remaining });
          send(ws, { type: 'poll_update', votes: computeCounts(), total: currentVotes.size });
        } else {
          const coolRemaining = pollTimer
            ? Math.max(0, (cooldownEnd || 0) - Date.now())
            : 0;
          send(ws, { type: 'cooldown', remaining_ms: coolRemaining });
        }
      }
    } catch(e) {}
  });
  ws.on('close', () => {
    if (role && clients[role]) clients[role].delete(ws);
  });
});

function send(ws, msg) {
  if (ws.readyState === 1) ws.send(JSON.stringify(msg));
}
function broadcast(role, msg) {
  const json = JSON.stringify(msg);
  for (const ws of (clients[role] || [])) {
    if (ws.readyState === 1) ws.send(json);
  }
}
function broadcastAll(msg) {
  broadcast('visualizer', msg);
  broadcast('overlay', msg);
}

// ── Poll state machine ────────────────────────────────────────────────────────
let state        = 'cooldown';
let pollTimer    = null;
let cooldownEnd  = 0;
let catIdx       = 0;
let currentPoll  = null;
let currentVotes = new Map(); // kik username → optionIndex

function startCooldown() {
  state = 'cooldown';
  currentPoll = null;
  currentVotes = new Map();
  cooldownEnd = Date.now() + COOLDOWN_MS;
  broadcastAll({ type: 'cooldown', remaining_ms: COOLDOWN_MS });
  pollTimer = setTimeout(startPoll, COOLDOWN_MS);
  console.log(`[poll] cooldown — next poll in ${COOLDOWN_MS / 1000}s`);
}

function startPoll() {
  const cat = CATEGORIES[catIdx % CATEGORIES.length];
  currentPoll  = { cat, startTime: Date.now() };
  currentVotes = new Map();
  state = 'active';
  const msg = {
    type: 'poll_start',
    category: cat.id,
    label: cat.label,
    options: cat.options,
    duration_ms: POLL_DURATION_MS,
    kik_bot: KIK_USERNAME,
  };
  broadcastAll(msg);
  pollTimer = setTimeout(endPoll, POLL_DURATION_MS);
  console.log(`[poll] started: ${cat.label} (${POLL_DURATION_MS / 1000}s)`);
}

function computeCounts() {
  if (!currentPoll) return [];
  const counts = new Array(currentPoll.cat.options.length).fill(0);
  for (const idx of currentVotes.values()) {
    if (idx >= 0 && idx < counts.length) counts[idx]++;
  }
  return counts;
}

function endPoll() {
  if (!currentPoll) return;
  const { cat } = currentPoll;
  const counts = computeCounts();
  const total  = currentVotes.size;

  // Find winner — highest count wins; tie → no winner
  let maxCount  = 0;
  let winnerIdx = -1;
  let tied      = false;
  for (let i = 0; i < counts.length; i++) {
    if (counts[i] > maxCount) {
      maxCount = counts[i]; winnerIdx = i; tied = false;
    } else if (counts[i] === maxCount && maxCount > 0) {
      tied = true;
    }
  }
  const hasWinner = winnerIdx >= 0 && !tied;

  const endMsg = {
    type: 'poll_end',
    winner_index: hasWinner ? winnerIdx : null,
    winner_label: hasWinner ? cat.options[winnerIdx] : null,
    votes: counts,
    total,
  };
  broadcastAll(endMsg);

  if (hasWinner) {
    const applyMsg = cat.applyMsg(winnerIdx);
    broadcast('visualizer', applyMsg);
    console.log(`[poll] winner: ${cat.options[winnerIdx]} (${counts[winnerIdx]}/${total} votes)`);
  } else {
    console.log(`[poll] tied — no change (counts: ${counts.join(', ')})`);
  }

  catIdx++;
  state = 'applying';
  // Brief pause so overlay can show the result, then cooldown
  pollTimer = setTimeout(startCooldown, 3_000);
}

// Start with an initial cooldown so everything is wired up before first poll
startCooldown();

// ── HTTP server (Kik webhook) ─────────────────────────────────────────────────
const httpServer = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/') {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('OK');
    return;
  }
  if (req.method === 'POST' && req.url === '/kik') {
    let body = '';
    req.on('data', d => { body += d; });
    req.on('end', () => {
      res.writeHead(200);
      res.end('OK');
      try {
        const data = JSON.parse(body);
        for (const { from, chatId, body: text } of parseInbound(data)) {
          handleKikMessage(from, chatId, text);
        }
      } catch(e) {}
    });
    return;
  }
  res.writeHead(404);
  res.end('Not found');
});

function handleKikMessage(from, chatId, text) {
  const lower = text.toLowerCase();

  if (lower === 'status') {
    let reply;
    if (state === 'active' && currentPoll) {
      const cat = currentPoll.cat;
      const elapsed = Date.now() - currentPoll.startTime;
      const secsLeft = Math.max(0, Math.round((POLL_DURATION_MS - elapsed) / 1000));
      reply = `Poll: ${cat.label} — ${secsLeft}s left\n`
        + cat.options.map((o, i) => `${i + 1}. ${o}`).join('\n')
        + '\n\nType a number to vote!';
    } else {
      reply = 'No active poll right now. Check back soon!';
    }
    kikReply(chatId, from, reply, KIK_USERNAME, KIK_API_KEY);
    return;
  }

  const num = parseInt(lower);

  if (state !== 'active' || !currentPoll) {
    kikReply(chatId, from, 'No active poll right now. Check back soon!', KIK_USERNAME, KIK_API_KEY);
    return;
  }

  const maxOpts = currentPoll.cat.options.length;
  if (isNaN(num) || num < 1 || num > maxOpts) {
    const opts = currentPoll.cat.options.map((o, i) => `${i + 1}. ${o}`).join('\n');
    kikReply(chatId, from, `Send a number 1–${maxOpts} to vote:\n${opts}`, KIK_USERNAME, KIK_API_KEY);
    return;
  }

  const optIdx = num - 1;
  const isChange = currentVotes.has(from) && currentVotes.get(from) !== optIdx;
  currentVotes.set(from, optIdx);

  const counts = computeCounts();
  broadcast('overlay', { type: 'poll_update', votes: counts, total: currentVotes.size });

  const elapsed   = Date.now() - currentPoll.startTime;
  const secsLeft  = Math.max(0, Math.round((POLL_DURATION_MS - elapsed) / 1000));
  const label     = currentPoll.cat.options[optIdx];
  const reply     = isChange
    ? `Changed to "${label}"! Results in ${secsLeft}s.`
    : `✓ Voted for "${label}"! Results in ${secsLeft}s.`;
  kikReply(chatId, from, reply, KIK_USERNAME, KIK_API_KEY);
  console.log(`[vote] ${from} → ${label}`);
}

httpServer.listen(HTTP_PORT, () => {
  console.log(`Piano MIDI Visualiser — Audience Vote Server`);
  console.log(`  HTTP (Kik webhook): http://localhost:${HTTP_PORT}/kik`);
  console.log(`  WebSocket (overlay/visualizer): ws://localhost:${WS_PORT}`);
  if (!KIK_USERNAME) console.log(`  Kik: no credentials set (KIK_USERNAME / KIK_API_KEY) — replies logged only`);
});
