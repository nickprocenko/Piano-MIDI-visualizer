'use strict';

/**
 * TwitchBot – optional Twitch chat integration.
 *
 * When enabled it listens for chat commands (e.g. "!theme neon") and forwards
 * them to a callback so the server can update the active config and broadcast
 * changes to all connected visualizer clients.
 *
 * This is a thin stub – full implementation requires the `tmi.js` package
 * and valid OAuth credentials in config.json.
 */
class TwitchBot {
  /**
   * @param {{ channel: string, oauth: string }} config
   * @param {(command: string, args: string[]) => void} onCommand
   */
  constructor(config, onCommand) {
    this._channel = config.channel;
    this._oauth = config.oauth;
    this._onCommand = onCommand;
    this._client = null;
  }

  /** Connect to Twitch IRC. Does nothing if credentials are not configured. */
  async connect() {
    if (!this._channel || !this._oauth) {
      console.log('[Twitch] No channel/oauth configured – Twitch integration disabled.');
      return;
    }

    try {
      // Dynamically require tmi.js so it is truly optional at runtime.
      const tmi = require('tmi.js');  // eslint-disable-line global-require
      this._client = new tmi.Client({
        identity: { username: 'midi_visualizer_bot', password: this._oauth },
        channels: [this._channel],
      });

      this._client.on('message', (_channel, _tags, message, self) => {
        if (self) return;
        if (!message.startsWith('!')) return;
        const [command, ...args] = message.slice(1).split(' ');
        this._onCommand(command.toLowerCase(), args);
      });

      await this._client.connect();
      console.log(`[Twitch] Connected to #${this._channel}`);
    } catch (err) {
      console.error('[Twitch] Failed to connect:', err.message);
    }
  }

  disconnect() {
    if (this._client) this._client.disconnect();
  }
}

module.exports = TwitchBot;
