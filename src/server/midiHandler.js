'use strict';

const midi = require('midi');
const { EventEmitter } = require('events');

/**
 * MidiHandler wraps the `midi` package and emits `noteOn` / `noteOff` events.
 *
 * Events:
 *   noteOn  (note: number, velocity: number)
 *   noteOff (note: number)
 */
class MidiHandler extends EventEmitter {
  constructor(deviceName = '') {
    super();
    this._input = new midi.Input();
    this._deviceName = deviceName;
  }

  /**
   * Open the MIDI input that matches deviceName (partial, case-insensitive).
   * Falls back to port 0 if no name is given or no match is found.
   */
  open() {
    const portCount = this._input.getPortCount();
    if (portCount === 0) {
      console.warn('[MIDI] No MIDI input ports found.');
      return;
    }

    let portIndex = 0;
    if (this._deviceName) {
      for (let i = 0; i < portCount; i++) {
        if (this._input.getPortName(i).toLowerCase().includes(this._deviceName.toLowerCase())) {
          portIndex = i;
          break;
        }
      }
    }

    console.log(`[MIDI] Opening port ${portIndex}: ${this._input.getPortName(portIndex)}`);
    this._input.openPort(portIndex);
    this._input.ignoreTypes(false, false, false);

    this._input.on('message', (_deltaTime, message) => {
      const [status, note, velocity] = message;
      const type = status & 0xf0;

      if (type === 0x90 && velocity > 0) {
        this.emit('noteOn', note, velocity);
      } else if (type === 0x80 || (type === 0x90 && velocity === 0)) {
        this.emit('noteOff', note);
      }
    });
  }

  /** List available MIDI input port names to the console. */
  listPorts() {
    const count = this._input.getPortCount();
    console.log(`[MIDI] Available input ports (${count}):`);
    for (let i = 0; i < count; i++) {
      console.log(`  [${i}] ${this._input.getPortName(i)}`);
    }
  }

  close() {
    this._input.closePort();
  }
}

module.exports = MidiHandler;
