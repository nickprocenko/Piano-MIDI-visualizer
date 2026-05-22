# Audience Vote Server

Node.js server that lets your Kik audience vote on visual changes to the Piano MIDI Visualiser in real time. Votes come in via a Kik bot; results appear as a corner-card overlay in OBS.

## How it works

1. The OBS overlay (`docs/overlay.html`) shows a poll card in the stream corner.
2. Viewers open Kik on their phone, message your bot with **1**, **2**, **3**, or **4**.
3. The server tallies votes and updates the overlay live.
4. After 30 s the winner is applied to the visualiser instantly.
5. A 15 s cooldown runs, then the next category poll starts.

**Vote categories** (random rotation, never repeats back-to-back):
- Note Theme — Rainbow / Octave Rainbow / Fire / Ice / Sunset
- Performance — Riders on the Storm / Moonlight Sonata / Light My Fire / Claire de Lune *(applies full visual preset)*
- Trail Colour — Ocean Blue / Sunset Red / Forest Green / Neon Purple
- Trail Speed — Slow / Normal / Fast / Very Fast
- Effects — Sparks On / Off / Smoke On / Off
- Fluid Effect — Default / Smoke / Fire / Storm / Gentle / Explosion

**Viewer commands:**

| Message | What happens |
|---------|-------------|
| `1`–`N` (poll active) | Casts your vote; bot confirms with time remaining |
| `!suggest <name>` | Fuzzy-matches an option and queues it for the next poll; bot replies with queue position |
| `status` | Shows the active poll and options |
| `!help` | Lists all categories, options, and commands |

---

## Setup

### 1. Register a Kik bot

Go to **https://dev.kik.com**, sign in, and create a bot. Save:
- **Bot username** (e.g. `pianonick`)
- **API key**

### 2. Install dependencies

```bash
cd server
npm install
```

### 3. Configure environment

Set the env vars before starting the server (or create a `.env` file and load with [dotenv](https://www.npmjs.com/package/dotenv)):

```bash
export KIK_USERNAME=your_bot_username
export KIK_API_KEY=your_api_key
```

Optional overrides:
```bash
export HTTP_PORT=8765   # Kik webhook port (default 8765)
export WS_PORT=8766     # WebSocket port for overlay + visualiser (default 8766)
export POLL_MS=30000    # Poll duration in ms (default 30000)
export COOL_MS=15000    # Cooldown between polls in ms (default 15000)
```

### 4. Start the server

```bash
node server.js
```

You should see:
```
Piano MIDI Visualiser — Audience Vote Server
  HTTP (Kik webhook): http://localhost:8765/kik
  WebSocket (overlay/visualizer): ws://localhost:8766
```

### 5. Expose the webhook with ngrok

```bash
ngrok http 8765
```

Copy the HTTPS forwarding URL (e.g. `https://abc123.ngrok.app`).

### 6. Register the Kik webhook

```bash
curl -X POST https://api.kik.com/v1/config \
  -u "YOUR_BOT_USERNAME:YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"webhook":"https://abc123.ngrok.app/kik","features":{"manuallySendReadReceipts":false,"receiveReadReceipts":false,"receiveDeliveryReceipts":false,"receiveIsTyping":false}}'
```

### 7. Add the OBS browser source

In OBS:
1. Add Source → **Browser**
2. URL: `file:///path/to/docs/overlay.html`  *(or full absolute path on your machine)*
3. Width: **1920**, Height: **1080**
4. Tick **"Shutdown source when not visible"** OFF
5. Tick **"Refresh browser when scene becomes active"** OFF

### 8. Connect the visualiser

Open `docs/index.html` → **Settings** → **Audience** tab:
- WebSocket URL: `ws://localhost:8766`
- Click **Connect**

### 9. Tell your audience

Put this in your stream description or chat:
> **"Send me a message on Kik at @YOUR_BOT_USERNAME! Type 1, 2, 3, or 4 to vote on the visuals."**

---

## Testing without Kik

Simulate a vote with curl:
```bash
curl -X POST http://localhost:8765/kik \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"from":"testviewer","chatId":"abc123","type":"text","body":"2"}]}'
```

Without Kik credentials set, bot replies are printed to the server console instead of sent.

---

## Adding more platforms (Twitch, YouTube)

Each platform adapter should call the same internal function: export a `receiveVote(username, optionIndex)` or replicate the `currentVotes.set(from, optIdx)` + `broadcast` pattern from `server.js`. The poll state machine is platform-agnostic.
