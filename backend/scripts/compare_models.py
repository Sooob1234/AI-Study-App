"""Transcribe one audio file with one Whisper model and print the result."""

import os
import sys
import time

from faster_whisper import WhisperModel


def notice(title: str, message: str) -> None:
    print(f"::notice title={title}::{message.replace(chr(10), ' ')}", flush=True)


def main() -> int:
    name = os.environ["WHISPER_MODEL"]
    path = sys.argv[1]

    started = time.time()
    model = WhisperModel(name, device="cpu", compute_type="int8")
    loaded = time.time() - started

    started = time.time()
    pieces, info = model.transcribe(path, language="fa", vad_filter=True)
    text = " ".join(piece.text.strip() for piece in pieces)
    took = time.time() - started

    notice(
        f"{name} 0 timing",
        f"audio={info.duration:.0f}s load={loaded:.0f}s transcribe={took:.0f}s "
        f"speed={took / info.duration:.2f}x of audio length chars={len(text)} cores={os.cpu_count()}",
    )
    for index in range(0, len(text), 600):
        notice(f"{name} {index // 600 + 1} text", text[index:index + 600])

    return 0


if __name__ == "__main__":
    sys.exit(main())
