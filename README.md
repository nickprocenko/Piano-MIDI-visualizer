# Piano MIDI Visualizer

A full-screen, real-time piano MIDI visualizer for live performances.  
Designed to run locally on Windows — no internet required.

## Features (Phase 1)
- Full-screen borderless window (no browser, no internet)
- Main menu with **START**, **SETTINGS**, and **QUIT**
- Placeholder note highway screen (press **ESC** to return to menu)
- 60 fps game loop

## Planned
- Real-time MIDI input (Roland JUNO-DS and other USB MIDI devices)
- 88-key piano rendering with key highlights
- Falling-note highway with coloured bars
- Audience-controlled colours via Twitch/TikTok chat
- ESP32 LED light synchronisation

## Requirements
- Python 3.10+
- [pygame](https://www.pygame.org/)

## How to run

```bash
pip install -r requirements.txt
python main.py
```

Press **ESC** from the highway placeholder to return to the main menu.  
Click **QUIT** or close the window to exit.


