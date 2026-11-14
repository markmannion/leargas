"""Voice I/O via ElevenLabs: speech-to-text for questions, text-to-speech for answers.

The API key stays server side (ELEVENLABS_API_KEY in the environment or the repo's .env);
the browser only talks to these endpoints.

    GET  /voice/status       -> {"enabled": bool}
    POST /voice/transcribe   raw audio body (any type MediaRecorder gives) -> {"text", "language_code"}
    POST /voice/speak        {"text": "..."} -> audio/mpeg
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

ELEVEN_BASE = "https://api.elevenlabs.io/v1"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
REPO = Path(__file__).resolve().parents[2]

router = APIRouter(prefix="/voice", tags=["voice"])


def _load_env() -> None:
    env = REPO / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def _key() -> str:
    k = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not k:
        raise HTTPException(503, "Voice is not configured (set ELEVENLABS_API_KEY).")
    return k


def _timeout() -> float:
    return float(os.environ.get("ELEVENLABS_TIMEOUT", 30))


def _upstream_error(r: httpx.Response) -> HTTPException:
    return HTTPException(502, f"ElevenLabs {r.status_code}: {r.text[:300]}")


@router.get("/status")
def status() -> dict:
    return {"enabled": bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())}


@router.post("/transcribe")
async def transcribe(request: Request) -> dict:
    key = _key()
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "Empty audio body.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Recording too long.")
    ctype = request.headers.get("content-type", "audio/webm").split(";")[0]
    ext = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/wav": "wav", "audio/mpeg": "mp3"}.get(ctype, "webm")
    async with httpx.AsyncClient(timeout=_timeout()) as c:
        r = await c.post(
            f"{ELEVEN_BASE}/speech-to-text",
            headers={"xi-api-key": key},
            data={"model_id": os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v1")},
            files={"file": (f"question.{ext}", audio, ctype)},
        )
    if r.status_code != 200:
        raise _upstream_error(r)
    j = r.json()
    return {"text": (j.get("text") or "").strip(), "language_code": j.get("language_code")}


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/speak")
async def speak(req: SpeakRequest) -> Response:
    key = _key()
    voice = os.environ.get("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    async with httpx.AsyncClient(timeout=_timeout()) as c:
        r = await c.post(
            f"{ELEVEN_BASE}/text-to-speech/{voice}",
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key, "Accept": "audio/mpeg"},
            json={"text": req.text, "model_id": os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_flash_v2_5")},
        )
    if r.status_code != 200:
        raise _upstream_error(r)
    return Response(content=r.content, media_type="audio/mpeg")
