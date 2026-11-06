from pathlib import Path
import sys
import urllib.request

KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin"

def download_file_with_progress(url: str, dest_path: Path) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest_path.with_suffix(".tmp")
    print(f"Downloading {dest_path.name}...")

    def progress_callback(blocks_transferred: int, block_size: int, total_size: int) -> None:
        transferred = blocks_transferred * block_size
        if total_size > 0:
            percent = min(100.0, (transferred / total_size) * 100.0)
            mb = transferred / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            bar_len = 30
            filled = int(bar_len * percent / 100.0)
            bar = "=" * filled + "-" * (bar_len - filled)
            sys.stdout.write(f"\r[{bar}] {percent:.1f}% ({mb:.1f}/{total_mb:.1f} MB)")
            sys.stdout.flush()

    try:
        urllib.request.urlretrieve(url, temp_path, reporthook=progress_callback)
        print()
        temp_path.replace(dest_path)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise e

def ensure_models(models_dir: Path | None = None) -> tuple[Path, Path]:
    if models_dir is None:
        # Check current working directory models/, then ~/.cache/kokoro
        local_dir = Path("models").resolve()
        cache_dir = Path.home() / ".cache" / "kokoro-onnx"
        if (local_dir / "kokoro-v1.0.onnx").exists() and (local_dir / "voices-v1.0.bin").exists():
            models_dir = local_dir
        elif (cache_dir / "kokoro-v1.0.onnx").exists() and (cache_dir / "voices-v1.0.bin").exists():
            models_dir = cache_dir
        else:
            models_dir = local_dir

    model_path = models_dir / "kokoro-v1.0.onnx"
    voices_path = models_dir / "voices-v1.0.bin"

    if not model_path.exists():
        download_file_with_progress(KOKORO_MODEL_URL, model_path)
    if not voices_path.exists():
        download_file_with_progress(VOICES_URL, voices_path)

    return model_path, voices_path
