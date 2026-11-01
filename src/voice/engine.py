"""
FRIDAY voice engines.

- STT: local faster-whisper (runs on-device; works in any browser, including Brave,
  which blocks the built-in Web Speech API).
- TTS: macOS `say` using a British male voice (Daniel) for the Jarvis butler accent.
"""
import io
import re
import wave
import logging
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger("FRIDAY.Voice")

STT_MODEL_SIZE = "base.en"
# Prompt biases Whisper toward the assistant's vocabulary.
STT_PROMPT = "FRIDAY, Jarvis, open Canva, open Safari, Notes, Calendar, Terminal, second brain, sir."

TTS_VOICE = "Daniel"          # British male, closest built-in match to Jarvis
TTS_RATE_WPM = 172            # measured, slightly unhurried butler cadence
TTS_MAX_CHARS = 1200

_model = None
_model_lock = threading.Lock()


def _get_model():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            logger.info(f"Loading Whisper model '{STT_MODEL_SIZE}' (first run downloads it)...")
            _model = WhisperModel(STT_MODEL_SIZE, device="cpu", compute_type="int8")
            logger.info("Whisper model ready.")
    return _model


def warmup_stt() -> None:
    try:
        _get_model()
    except Exception as e:
        logger.warning(f"Whisper warmup failed: {e}")


def _wav_to_float32_16k(audio_bytes: bytes) -> np.ndarray:
    """Decode 16-bit PCM WAV bytes to mono float32 at 16 kHz."""
    with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
        channels = wf.getnchannels()
        rate = wf.getframerate()
        width = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())
    if width != 2:
        raise ValueError("Only 16-bit PCM WAV is supported")
    pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    if rate != 16000 and len(pcm) > 0:
        target_len = int(len(pcm) * 16000 / rate)
        pcm = np.interp(
            np.linspace(0, len(pcm) - 1, target_len), np.arange(len(pcm)), pcm
        ).astype(np.float32)
    return pcm


def transcribe_wav(audio_bytes: bytes) -> str:
    """Transcribe a PCM WAV utterance."""
    model = _get_model()
    audio = _wav_to_float32_16k(audio_bytes)
    segments, _info = model.transcribe(
        audio,
        language="en",
        beam_size=1,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        condition_on_previous_text=False,
        initial_prompt=STT_PROMPT,
        no_speech_threshold=0.6,
    )
    text = " ".join(s.text.strip() for s in segments).strip()
    # Whisper sometimes hallucinates on near-silence
    if text.lower().strip(" .!") in {"you", "thank you", "thanks for watching", "bye"}:
        return ""
    return text


def clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[Switched to fallback brain[^\]]*\]", " ", text)
    text = re.sub(r"\*\(Notice:.*?\)\*", " ", text, flags=re.S)
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:TTS_MAX_CHARS]


def synthesize_wav(text: str, voice: str = TTS_VOICE) -> bytes:
    """Render speech to 22.05 kHz 16-bit WAV bytes using macOS `say`."""
    text = clean_for_speech(text)
    if not text:
        return b""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "speech.wav"
        cmd = [
            "/usr/bin/say", "-v", voice, "-r", str(TTS_RATE_WPM),
            "--data-format=LEI16@22050", "-o", str(out), "--", text,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=60)
        if result.returncode != 0 or not out.exists():
            raise RuntimeError(result.stderr.decode(errors="ignore") or "say failed")
        return out.read_bytes()
