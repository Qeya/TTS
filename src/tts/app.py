from __future__ import annotations
import argparse
import asyncio
import os
from pathlib import Path
import readline  # Enable readline history and navigation in terminal
import sys

from kokoro_onnx import Kokoro
from tts.audio import (
    StreamPlayer,
    find_output_device,
    get_default_monitor_device,
    list_output_devices,
)
from tts.downloader import ensure_models

SAMPLE_RATE = 24000

HELP_TEXT = """
Available Commands:
  /voice <name>     Change voice (e.g., /voice af_heart, /voice am_michael, /voice bf_emma)
  /voices           List popular available voices
  /speed <val>      Set speech speed multiplier (e.g., /speed 1.15)
  /monitor <on|off> Toggle hearing speech through your headphones/speakers
  /device           Show current audio device settings
  /device <id|name> Switch target audio device
  /devices          List all detected audio output devices
  /clear            Clear screen
  /help             Show this help message
  /exit or quit     Exit program
"""

VOICE_CATEGORIES = {
    "American Female (af)": [
        "af_heart",
        "af_alloy",
        "af_aoede",
        "af_bella",
        "af_jessica",
        "af_kore",
        "af_nicole",
        "af_nova",
        "af_river",
        "af_sarah",
        "af_sky",
    ],
    "American Male (am)": [
        "am_adam",
        "am_echo",
        "am_eric",
        "am_fenrir",
        "am_liam",
        "am_michael",
        "am_onyx",
        "am_puck",
    ],
    "British Female (bf)": ["bf_alice", "bf_emma", "bf_isabella", "bf_lily"],
    "British Male (bm)": ["bm_daniel", "bm_fable", "bm_george", "bm_lewis"],
}


def print_banner(
    target_name: str, voice: str, speed: float, monitor: bool, monitor_name: str | None
) -> None:
    print("=" * 65)
    print("  Kokoro 82M TTS -> Discord Streamer")
    print("=" * 65)
    print(f"  Target Device : {target_name} (Set Discord Input to this!)")
    print(f"  Voice         : {voice}")
    print(f"  Speed         : {speed:.2f}x")
    mon_status = f"Enabled ({monitor_name})" if monitor and monitor_name else "Disabled"
    print(f"  Monitor Audio : {mon_status}")
    print("-" * 65)
    print("  Type any message and press [Enter] to speak.")
    print("  Type /help for options or /exit to quit.")
    print("=" * 65 + "\n")


def display_voices(all_voices: list[str]) -> None:
    print("\n--- Available Voices ---")
    voice_set = set(all_voices)
    for category, sample_voices in VOICE_CATEGORIES.items():
        present = [v for v in sample_voices if v in voice_set]
        if present:
            print(f"  {category}:")
            print("    " + ", ".join(present))

    known = {v for cat in VOICE_CATEGORIES.values() for v in cat}
    others = [v for v in all_voices if v not in known]
    if others:
        print("  Other Voices:")
        print(
            "    "
            + ", ".join(others[:20])
            + (f" ... (+{len(others) - 20} more)" if len(others) > 20 else "")
        )
    print("------------------------\n")


async def stream_speech(
    kokoro: Kokoro,
    player: StreamPlayer,
    text: str,
    voice: str,
    speed: float,
) -> None:
    async for chunk, sr in kokoro.create_stream(text, voice=voice, speed=speed):
        player.write_chunk(chunk)


def run_cli() -> None:
    parser = argparse.ArgumentParser(
        description="Stream Kokoro 82M Text-to-Speech into BlackHole 2ch for Discord."
    )
    parser.add_argument(
        "-v",
        "--voice",
        default="af_heart",
        help="Kokoro voice name (default: af_heart)",
    )
    parser.add_argument(
        "-s",
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed multiplier (default: 1.0)",
    )
    parser.add_argument(
        "-d",
        "--device",
        default=None,
        help="Target output device index or name (default: auto-detect virtual cable)",
    )
    parser.add_argument(
        "-m",
        "--monitor",
        action="store_true",
        help="Mirror audio to your default headphones/speakers so you can hear it",
    )
    parser.add_argument(
        "--monitor-device",
        default=None,
        help="Explicit device name or index for audio monitoring",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List all available audio output devices and exit",
    )
    parser.add_argument(
        "--list-voices",
        action="store_true",
        help="List available Kokoro voices and exit",
    )

    args = parser.parse_args()

    if args.list_devices:
        print("\nAvailable Output Devices:")
        for dev in list_output_devices():
            print(
                f"  [{dev['index']}] {dev['name']} ({dev['max_output_channels']} channels)"
            )
        return

    model_path, voices_path = ensure_models()
    print("Loading Kokoro-82M ONNX model...")
    kokoro = Kokoro(str(model_path), str(voices_path))
    available_voices = kokoro.get_voices()

    if args.list_voices:
        display_voices(available_voices)
        return

    current_voice = args.voice
    if current_voice not in available_voices:
        print(
            f"[Warning] Voice '{current_voice}' not found in voices file. Falling back to 'af_heart'."
        )
        current_voice = (
            "af_heart" if "af_heart" in available_voices else available_voices[0]
        )

    try:
        target_idx, target_info = find_output_device(args.device)
    except Exception as e:
        print(f"[Error] Failed to find target device '{args.device}': {e}")
        print("\nAvailable devices:")
        for dev in list_output_devices():
            print(f"  [{dev['index']}] {dev['name']}")
        sys.exit(1)

    monitor_enabled = args.monitor
    monitor_idx = None
    monitor_name = None
    if monitor_enabled:
        if args.monitor_device:
            try:
                monitor_idx, mon_info = find_output_device(args.monitor_device)
                monitor_name = mon_info["name"]
            except Exception as e:
                print(f"[Warning] Specified monitor device not found: {e}")
        if monitor_idx is None:
            mon_pair = get_default_monitor_device()
            if mon_pair:
                monitor_idx, mon_info = mon_pair
                monitor_name = mon_info["name"]

    current_speed = max(0.5, min(2.5, args.speed))

    player = StreamPlayer(
        target_device_idx=target_idx,
        sample_rate=SAMPLE_RATE,
        monitor=monitor_enabled,
        monitor_device_idx=monitor_idx,
    )

    print_banner(
        target_name=target_info["name"],
        voice=current_voice,
        speed=current_speed,
        monitor=monitor_enabled,
        monitor_name=monitor_name,
    )

    try:
        while True:
            try:
                prompt_str = f"tts [{current_voice}]> "
                text = input(prompt_str).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting...")
                break

            if not text:
                continue

            # Command handling
            if text.startswith("/"):
                parts = text.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                if cmd in ("/exit", "/quit"):
                    print("Exiting...")
                    break
                elif cmd == "/help":
                    print(HELP_TEXT)
                    continue
                elif cmd == "/clear":
                    os.system("clear" if os.name != "nt" else "cls")
                    continue
                elif cmd == "/voices":
                    display_voices(available_voices)
                    continue
                elif cmd == "/devices":
                    print("\nAvailable Output Devices:")
                    for dev in list_output_devices():
                        mark = " *" if dev["index"] == target_idx else ""
                        print(f"  [{dev['index']}] {dev['name']}{mark}")
                    print()
                    continue
                elif cmd == "/device":
                    if not arg:
                        print(
                            f"Current Target Device: [{target_idx}] {target_info['name']}"
                        )
                        mon_disp = (
                            f"[{monitor_idx}] {monitor_name}"
                            if monitor_enabled and monitor_idx is not None
                            else "Off"
                        )
                        print(f"Monitor Device: {mon_disp}")
                    else:
                        try:
                            new_idx, new_info = find_output_device(
                                int(arg) if arg.isdigit() else arg
                            )
                            player.close()
                            target_idx, target_info = new_idx, new_info
                            player = StreamPlayer(
                                target_device_idx=target_idx,
                                sample_rate=SAMPLE_RATE,
                                monitor=monitor_enabled,
                                monitor_device_idx=monitor_idx,
                            )
                            print(
                                f"[OK] Switched target device to: [{target_idx}] {target_info['name']}"
                            )
                        except Exception as err:
                            print(f"[Error] Failed to switch device: {err}")
                    continue
                elif cmd == "/voice":
                    if not arg:
                        print(f"Current voice: {current_voice}")
                    elif arg in available_voices:
                        current_voice = arg
                        print(f"[OK] Voice set to '{current_voice}'")
                    else:
                        print(
                            f"[Error] Unknown voice '{arg}'. Type /voices to see list."
                        )
                    continue
                elif cmd == "/speed":
                    if not arg:
                        print(f"Current speed: {current_speed:.2f}x")
                    else:
                        try:
                            val = float(arg)
                            if 0.5 <= val <= 2.5:
                                current_speed = val
                                print(f"[OK] Speed set to {current_speed:.2f}x")
                            else:
                                print("[Error] Speed must be between 0.5 and 2.5.")
                        except ValueError:
                            print("[Error] Invalid number for speed.")
                    continue
                elif cmd == "/monitor":
                    if not arg:
                        print(
                            f"Monitor is currently {'ON' if monitor_enabled else 'OFF'}"
                        )
                    elif arg.lower() in ("on", "1", "true"):
                        if not monitor_enabled:
                            monitor_enabled = True
                            if monitor_idx is None:
                                mon_pair = get_default_monitor_device()
                                if mon_pair:
                                    monitor_idx, mon_info = mon_pair
                                    monitor_name = mon_info["name"]
                            player.close()
                            player = StreamPlayer(
                                target_device_idx=target_idx,
                                sample_rate=SAMPLE_RATE,
                                monitor=True,
                                monitor_device_idx=monitor_idx,
                            )
                        print(f"[OK] Monitor enabled ({monitor_name or 'Default'})")
                    elif arg.lower() in ("off", "0", "false"):
                        monitor_enabled = False
                        player.close()
                        player = StreamPlayer(
                            target_device_idx=target_idx,
                            sample_rate=SAMPLE_RATE,
                            monitor=False,
                        )
                        print("[OK] Monitor disabled")
                    else:
                        print("Usage: /monitor on | /monitor off")
                    continue
                else:
                    print(f"Unknown command '{cmd}'. Type /help for assistance.")
                    continue

            # Synthesize and stream
            try:
                asyncio.run(
                    stream_speech(kokoro, player, text, current_voice, current_speed)
                )
            except Exception as e:
                print(f"[TTS Error] {e}")

    finally:
        player.close()
        print("Audio streams closed. Goodbye!")
