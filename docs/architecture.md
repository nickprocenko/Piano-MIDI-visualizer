# Architecture Overview

## High-Level Flow

```
MIDI Device
    │
    │  USB / DIN
    ▼
┌─────────────────┐
│  Node.js Server │  src/server/index.js
│                 │
│  midiHandler.js │──► broadcasts noteOn / noteOff over WebSocket
│  twitchBot.js   │──► translates chat commands into config updates
│                 │
│  Express HTTP   │──► serves the browser client (src/client/)
└────────┬────────┘
         │  WebSocket (ws://)
         ▼
┌─────────────────┐
│ Browser Client  │  src/client/visualizer.js
│                 │
│  Canvas 2D      │──► renders piano roll & falling note blocks
└─────────────────┘
```

## Modules

### `src/server/midiHandler.js`
Wraps the `midi` npm package.  Emits `noteOn(note, velocity)` and `noteOff(note)` events from any connected MIDI input port.

### `src/server/twitchBot.js`
Optional Twitch IRC integration via `tmi.js`.  Listens for `!theme <name>` and `!speed <number>` chat commands and triggers a callback.  Disabled automatically when no channel/oauth is set in `config.json`.

### `src/server/index.js`
Entry point.  Glues together Express, WebSocketServer, MidiHandler, and TwitchBot.  Broadcasts MIDI events and config changes to all connected browser clients.

### `src/client/visualizer.js`
Pure browser-side code (no bundler required).  Connects to the WebSocket, receives note events, and renders a scrolling piano-roll animation on an HTML5 Canvas.  Supports three built-in themes (`default`, `neon`, `minimal`) and reconnects automatically on disconnect.

## Data Flow

1. A MIDI note-on message arrives on the device.
2. `MidiHandler` emits `noteOn(note, velocity)`.
3. `index.js` serialises it as `{ type: "noteOn", note, velocity }` and broadcasts it via WebSocket.
4. `visualizer.js` receives the message and calls `noteOn(midiNote)`, which spawns a falling note block on the canvas.
5. The animation loop (`requestAnimationFrame`) moves the block downward every frame until it reaches the piano keys at the bottom.

## Configuration

All settings live in `config.json` (see `config.example.json`).  The server injects `theme` and `noteSpeed` into the HTML page on first load; subsequent changes (e.g. from Twitch chat) are pushed live via WebSocket.
