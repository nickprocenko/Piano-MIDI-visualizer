'use strict';
const https = require('https');

function parseInbound(body) {
  return (body.messages || [])
    .filter(m => m.type === 'text')
    .map(m => ({ from: m.from, chatId: m.chatId, body: (m.body || '').trim() }));
}

function kikReply(chatId, toUsername, text, botUsername, apiKey) {
  if (!botUsername || !apiKey) {
    console.log(`[kik → ${toUsername}]: ${text}`);
    return;
  }
  const payload = JSON.stringify({
    messages: [{ chatId, type: 'text', to: toUsername, body: text }],
  });
  const auth = Buffer.from(`${botUsername}:${apiKey}`).toString('base64');
  const opts = {
    hostname: 'api.kik.com',
    path: '/v1/message',
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Basic ${auth}`,
      'Content-Length': Buffer.byteLength(payload),
    },
  };
  const req = https.request(opts, r => r.resume());
  req.on('error', () => {});
  req.write(payload);
  req.end();
}

module.exports = { parseInbound, kikReply };
