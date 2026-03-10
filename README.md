# Piano MIDI Visualizer

A real-time piano roll / note highway visualizer that accepts MIDI input and streams beautiful animations to a web browser or live-streaming platforms such as Twitch.

---

## Features

- 🎹 **Live MIDI input** – reads notes from any connected MIDI device via the Node.js [`midi`](https://www.npmjs.com/package/midi) package on the server
- 🖥️ **Piano-roll visualization** – animated note highway rendered on an HTML5 Canvas
- 🌐 **Web server** – serve the visualizer to any browser on your local network
- 📡 **Wireless control** – adjust settings and trigger animations from a web page or a Twitch chat bot
- 🎨 **Customizable themes** – change colours, speed, key labels, and more through a simple config file

---

## Project Structure

```
Piano-MIDI-visualizer/
├── src/
│   ├── client/          # Browser-side code (HTML, CSS, JavaScript canvas renderer)
│   │   ├── index.html
│   │   ├── style.css
│   │   └── visualizer.js
│   └── server/          # Node.js backend (MIDI capture, WebSocket, Twitch bot)
│       ├── index.js
│       ├── midiHandler.js
│       └── twitchBot.js
├── docs/                # Additional documentation and design notes
├── .gitignore
├── CONTRIBUTING.md
├── package.json
└── README.md
```

---

## Prerequisites

| Tool | Version |
|------|---------|
| [Node.js](https://nodejs.org/) | 18 LTS or newer |
| npm | bundled with Node.js |
| A MIDI interface or virtual MIDI port | — |

---

## Getting Started

```bash
# 1. Clone the repository
git clone https://github.com/nickprocenko/Piano-MIDI-visualizer.git
cd Piano-MIDI-visualizer

# 2. Install dependencies
npm install

# 3. (Optional) Copy and edit the configuration
cp config.example.json config.json

# 4. Start the server
npm start
```

Then open **http://localhost:3000** in your browser.  
Connect your MIDI device and start playing – notes will appear in the visualizer automatically.

---

## Configuration

All run-time settings live in `config.json` (copy from `config.example.json`):

| Key | Default | Description |
|-----|---------|-------------|
| `port` | `3000` | HTTP / WebSocket server port |
| `midiDevice` | `""` | Partial name of the MIDI input device to use (empty = first available) |
| `theme` | `"default"` | Visual theme (`"default"`, `"neon"`, `"minimal"`) |
| `noteSpeed` | `4` | Pixels per frame the note blocks fall |
| `twitch.channel` | `""` | Twitch channel name for chat-bot integration |
| `twitch.oauth` | `""` | OAuth token for the Twitch bot account |

---

## Contributing

Contributions are welcome! Please read **[CONTRIBUTING.md](CONTRIBUTING.md)** first to learn how to set up the development environment and submit changes.

---

## License

This project is released under the [MIT License](LICENSE).
