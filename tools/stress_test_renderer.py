from __future__ import annotations

import argparse
from pathlib import Path
import random
import sys
import time

import pygame

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.note_fx import NoteEffectRenderer


def build_trails(count: int, width: int, height: int) -> list[dict[str, float | bool | list[dict[str, float]]]]:
    trails: list[dict[str, float | bool | list[dict[str, float]]]] = []
    for _ in range(count):
        bar_w = random.uniform(8.0, 26.0)
        top_y = random.uniform(height * 0.05, height * 0.65)
        bottom_y = min(height - 8.0, top_y + random.uniform(120.0, 520.0))
        trail: dict[str, float | bool | list[dict[str, float]]] = {
            "x": random.uniform(20.0, width - 20.0),
            "top_y": top_y,
            "bottom_y": bottom_y,
            "width": bar_w,
            "released": random.random() > 0.55,
            "age_ms": random.uniform(0.0, 800.0),
        }
        trails.append(trail)
    return trails


def run_case(width: int, height: int, trail_count: int, frames: int, glow_strength: int) -> tuple[float, float]:
    screen = pygame.Surface((width, height), pygame.SRCALPHA)
    renderer = NoteEffectRenderer(screen)
    trails = build_trails(trail_count, width, height)

    style = {
        "color_r": 22,
        "color_g": 180,
        "color_b": 255,
        "interior_r": 160,
        "interior_g": 245,
        "interior_b": 255,
        "edge_roundness_px": 9,
        "outer_edge_width_px": 2,
        "decay_speed": 95,
        "decay_value": 22,
        "inner_blend_percent": 35,
        "glow_strength_percent": glow_strength,
        "effect_glow_enabled": 1,
        "effect_highlight_enabled": 1,
        "effect_sparks_enabled": 1,
        "effect_smoke_enabled": 1,
        "highlight_strength_percent": 70,
        "spark_amount_percent": 100,
        "smoke_amount_percent": 100,
    }

    start = time.perf_counter()
    for frame in range(frames):
        renderer.begin_frame()
        phase = frame * 0.025
        for i, trail in enumerate(trails):
            wobble = (i % 7 - 3) * 0.35
            trail["top_y"] = float(trail["top_y"]) + wobble
            trail["bottom_y"] = float(trail["bottom_y"]) + wobble
            trail["x"] = max(8.0, min(width - 8.0, float(trail["x"]) + ((i % 5) - 2) * 0.12 + phase * 0.02))
            renderer.draw_trail(trail, style)
        renderer.end_frame()
    elapsed = time.perf_counter() - start

    avg_ms = (elapsed / max(1, frames)) * 1000.0
    fps = frames / max(0.0001, elapsed)
    return avg_ms, fps


def main() -> None:
    parser = argparse.ArgumentParser(description="Stress-test piano note renderer.")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--trails", type=int, default=140)
    parser.add_argument("--frames", type=int, default=240)
    args = parser.parse_args()

    pygame.init()
    try:
        no_bloom_ms, no_bloom_fps = run_case(args.width, args.height, args.trails, args.frames, glow_strength=0)
        bloom_ms, bloom_fps = run_case(args.width, args.height, args.trails, args.frames, glow_strength=85)
    finally:
        pygame.quit()

    print(f"Renderer stress test at {args.width}x{args.height}, trails={args.trails}, frames={args.frames}")
    print(f"No bloom  : {no_bloom_ms:.2f} ms/frame  ({no_bloom_fps:.1f} FPS)")
    print(f"With bloom: {bloom_ms:.2f} ms/frame  ({bloom_fps:.1f} FPS)")
    print(f"Bloom cost: {bloom_ms - no_bloom_ms:.2f} ms/frame")


if __name__ == "__main__":
    main()