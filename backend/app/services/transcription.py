"""Turning speech in an audio file into timed text.

The work is done on this computer by an open speech-recognition model
(Whisper, through the faster-whisper package). No outside service, account
or payment is involved. The packages are optional: they are listed in
requirements-audio.txt, and without them the app runs but refuses audio.

This belongs to the source-processing layer: it only writes down what was
said. It does not summarise or interpret.
"""

import logging
import os
import threading
from dataclasses import dataclass

# TRANSCRIPTION_V1

logger = logging.getLogger(__name__)

# Which Whisper model to use. Larger models are more accurate and slower:
# tiny, base, small, medium, large-v3.
MODEL_NAME = os.getenv("WHISPER_MODEL", "small")

# Reasons reported together with FAILED.
TRANSCRIBER_UNAVAILABLE = "TRANSCRIBER_UNAVAILABLE"
TRANSCRIPTION_FAILED = "TRANSCRIPTION_FAILED"
NO_SPEECH = "NO_SPEECH"


class AudioError(Exception):
    """The file is not usable audio."""


class TranscriptionError(Exception):
    """An audio file could not be transcribed; `code` says why."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass
class Transcript:
    language: str | None
    # (start_seconds, end_seconds, text), in order.
    segments: list[tuple[float, float, str]]


def is_available() -> bool:
    """Whether the optional audio packages are installed."""
    try:
        import av  # noqa: F401
        import faster_whisper  # noqa: F401
    except Exception:
        return False

    return True


def probe_audio(path: str) -> float:
    """Return the length of an audio file in seconds.

    Raises AudioError if the file cannot be read as audio.
    """
    import av

    try:
        with av.open(path) as container:
            if not container.streams.audio:
                raise AudioError("The file has no audio")

            duration = container.duration
            if duration is None:
                stream = container.streams.audio[0]
                if stream.duration is None or stream.time_base is None:
                    raise AudioError("The length of the audio is unknown")
                return float(stream.duration * stream.time_base)

            return duration / av.time_base
    except AudioError:
        raise
    except Exception:
        raise AudioError("The file is not valid audio")


_model = None
_model_lock = threading.Lock()
# Recognition uses every processor core; two at once would only slow both.
_transcribe_lock = threading.Lock()


def _get_model():
    global _model

    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            # The model is downloaded the first time and then kept on disk.
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")

        return _model


def transcribe(path: str) -> Transcript:
    """Transcribe an audio file. Raises TranscriptionError when impossible."""
    try:
        model = _get_model()
    except Exception:
        logger.exception("The speech-recognition model could not be loaded")
        raise TranscriptionError(TRANSCRIBER_UNAVAILABLE)

    try:
        with _transcribe_lock:
            # vad_filter skips the silent parts of the recording.
            pieces, info = model.transcribe(path, vad_filter=True)
            segments = [
                (float(piece.start), float(piece.end), piece.text.strip())
                for piece in pieces
            ]
    except Exception:
        logger.exception("Transcription of %s failed", path)
        raise TranscriptionError(TRANSCRIPTION_FAILED)

    return Transcript(language=info.language, segments=segments)
