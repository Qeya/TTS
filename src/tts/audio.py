from __future__ import annotations
import threading
from typing import Any
import numpy as np
import sounddevice as sd

def list_output_devices() -> list[dict[str, Any]]:
    """Return all available audio output devices."""
    devices = sd.query_devices()
    output_devs = []
    for idx, d in enumerate(devices):
        if d.get("max_output_channels", 0) > 0:
            output_devs.append({"index": idx, **d})
    return output_devs

COMMON_VIRTUAL_CABLES = [
    "blackhole",       # macOS (BlackHole 2ch / 16ch)
    "cable input",     # Windows (VB-Audio Virtual Cable)
    "vb-audio",        # Windows VB-Audio
    "virtualmic",      # Linux PulseAudio/PipeWire sink
    "null output",     # Linux module-null-sink
    "virtual audio",   # Generic virtual audio driver
]

def find_output_device(name_or_idx: str | int | None = None) -> tuple[int, dict[str, Any]]:
    """Find an output device by index or partial name. Defaults to detected virtual audio cable or system default."""
    all_devs = sd.query_devices()

    if isinstance(name_or_idx, int):
        if 0 <= name_or_idx < len(all_devs):
            dev = all_devs[name_or_idx]
            if dev.get("max_output_channels", 0) > 0:
                return name_or_idx, dev
            raise ValueError(f"Device #{name_or_idx} '{dev['name']}' has no output channels.")
        raise IndexError(f"Device index {name_or_idx} out of range.")

    if name_or_idx:
        query = str(name_or_idx).lower().strip()
        for idx, d in enumerate(all_devs):
            if d.get("max_output_channels", 0) > 0 and query in d["name"].lower():
                return idx, d
        raise ValueError(f"No output audio device matching '{name_or_idx}' found.")

    # Auto-detect known virtual audio cables (macOS BlackHole, Windows VB-Cable, Linux null-sink)
    for cable_kw in COMMON_VIRTUAL_CABLES:
        for idx, d in enumerate(all_devs):
            if d.get("max_output_channels", 0) > 0 and cable_kw in d["name"].lower():
                return idx, d

    # Fallback to default output device if no virtual cable found
    default_out = sd.default.device[1]
    if default_out is not None and default_out >= 0:
        return default_out, all_devs[default_out]

    raise RuntimeError("No suitable audio output device found.")

def _is_virtual_device(device_name: str) -> bool:
    name_lower = device_name.lower()
    return any(kw in name_lower for kw in COMMON_VIRTUAL_CABLES)

def get_default_monitor_device() -> tuple[int, dict[str, Any]] | None:
    """Find the system default output device (e.g. headphones/speakers) for monitoring."""
    all_devs = sd.query_devices()
    default_out = sd.default.device[1]
    if default_out is not None and default_out >= 0:
        dev = all_devs[default_out]
        # Avoid picking a virtual cable as monitor if it was accidentally set as default output
        if not _is_virtual_device(dev["name"]) and dev.get("max_output_channels", 0) > 0:
            return default_out, dev

    # Otherwise look for built-in or headphones
    for idx, d in enumerate(all_devs):
        if d.get("max_output_channels", 0) > 0 and not _is_virtual_device(d["name"]):
            return idx, d
    return None

class StreamPlayer:
    """Manages audio playback to a target device (e.g., BlackHole) and optional monitor device."""

    def __init__(
        self,
        target_device_idx: int,
        sample_rate: int = 24000,
        monitor: bool = False,
        monitor_device_idx: int | None = None,
    ):
        self.target_idx = target_device_idx
        self.sample_rate = sample_rate
        self.monitor = monitor
        self.monitor_idx = monitor_device_idx

        target_info = sd.query_devices(self.target_idx)
        self.target_channels = min(2, target_info.get("max_output_channels", 1))

        self.target_stream = sd.OutputStream(
            samplerate=self.sample_rate,
            device=self.target_idx,
            channels=self.target_channels,
            dtype="float32",
        )
        self.target_stream.start()

        self.monitor_stream = None
        if self.monitor and self.monitor_idx is not None and self.monitor_idx != self.target_idx:
            try:
                mon_info = sd.query_devices(self.monitor_idx)
                mon_channels = min(2, mon_info.get("max_output_channels", 2))
                self.monitor_channels = mon_channels
                self.monitor_stream = sd.OutputStream(
                    samplerate=self.sample_rate,
                    device=self.monitor_idx,
                    channels=mon_channels,
                    dtype="float32",
                )
                self.monitor_stream.start()
            except Exception as e:
                print(f"[Warning] Could not initialize monitor stream: {e}")
                self.monitor_stream = None

    def _prepare_audio(self, audio: np.ndarray, channels: int) -> np.ndarray:
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.ndim == 1:
            if channels == 2:
                return np.column_stack([audio, audio])
            return audio.reshape(-1, 1)
        elif audio.ndim == 2:
            if audio.shape[1] == 1 and channels == 2:
                return np.column_stack([audio[:, 0], audio[:, 0]])
            return audio[:, :channels]
        return audio

    def write_chunk(self, audio: np.ndarray) -> None:
        """Write an audio chunk simultaneously to target and optional monitor stream."""
        target_data = self._prepare_audio(audio, self.target_channels)

        if self.monitor_stream is not None:
            mon_data = self._prepare_audio(audio, self.monitor_channels)

            def play_target():
                self.target_stream.write(target_data)

            def play_monitor():
                self.monitor_stream.write(mon_data)

            t1 = threading.Thread(target=play_target)
            t2 = threading.Thread(target=play_monitor)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        else:
            self.target_stream.write(target_data)

    def close(self) -> None:
        """Close audio streams cleanly."""
        try:
            self.target_stream.stop()
            self.target_stream.close()
        except Exception:
            pass

        if self.monitor_stream is not None:
            try:
                self.monitor_stream.stop()
                self.monitor_stream.close()
            except Exception:
                pass

    def __enter__(self) -> StreamPlayer:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
