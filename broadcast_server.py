#!/usr/bin/env python3
"""Local server for Ollama broadcast channel.
Serves static files and provides JSON APIs for listing/saving creations.
"""

from __future__ import annotations

import json
import math
import platform
import random
import re
import struct
import subprocess
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is expected to be installed
    psutil = None  # type: ignore[assignment]

try:
    import requests
except ImportError:  # pragma: no cover - requests is expected to be installed
    requests = None  # type: ignore[assignment]

BASE_DIR = Path(__file__).resolve().parent
ARCHIVE_DIR = BASE_DIR / "archive"
ARCHIVE_URL_PREFIX = "archive"
VER_FILE_RE = re.compile(r"^index-4\.7-VER(\d+)\.html$", re.IGNORECASE)

# --- Generation engine config (server is the single owner of the Ollama stream) ---
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "glm-4.7-flash-gpu"
FALLBACK_MODEL = "glm-4.7-flash:q4_k_M"
COOLDOWN_MS = 6000

# Rotating instruction list. Each generation cycle uses the NEXT prompt in order.
# The current position is persisted to disk (see PROMPT_STATE_FILE) so the rotation
# resumes from the next item even after the server is closed and reopened.
PROMPTS = [
    "Create a futuristic animated data dashboard in English only. Desktop and mobile compatible. After a 5s intro, autoplay a 25s zero-click scripted demo (~30s total). Vanilla JS only, same HTML file. Auto-cycle through: KPI cards pulsing, bar & line charts building, financial ticker streaming candles with P&L updates, weather time-lapse on a mini-map with storm alerts, and a lab experiment graph showing temperature rise. Each widget highlights in sequence, then zooms to one key insight.",
    "Create a futuristic animated OS and command center in English only. Desktop and mobile compatible. After a 5s intro, autoplay a 25s zero-click scripted demo (~30s total). Vanilla JS only, same HTML file. Auto-open a terminal app, type a command, switch windows, then return to desktop. Simulate an AI question, auto-type the reply with waveform animation. Pan a world map, ping threat targets, flash alerts, and update mission status boards. Finally rotate a holographic model, cycle its data layers, and pulse labels.",
    "Create a futuristic animated sci-fi explorer in English only. Desktop and mobile compatible. After a 5s intro, autoplay a 25s zero-click scripted demo (~30s total). Vanilla JS only, same HTML file. Fly camera through neon city streets with traffic, then cut to space station: tour life support, dock, and comms modules – each screen activates automatically. Next, orbit planets, trigger a hyperspace jump, scan and label discoveries. Finally drift through a particle universe where particles swarm into shapes (cube, sphere, logo) then disperse on cue.",
    "Create a futuristic animated commercial showcase in English only. Desktop and mobile compatible. After a 5s intro, autoplay a 25s zero-click scripted demo (~30s total). Vanilla JS only, same HTML file. Auto-stroll through a cyberpunk marketplace: flickering prices, animated banners, auto-add item to cart. Then carousel three products – each card expands and demos itself (spin, zoom, show specs). Finally auto-advance a startup pitch: problem slide, solution with chart build, metrics, and CTA button pulsing.",
    "Create a futuristic animated portfolio and museum in English only. Desktop and mobile compatible. After a 5s intro, autoplay a 25s zero-click scripted demo (~30s total). Vanilla JS only, same HTML file. Auto-scroll through project cards: each expands, plays a mini preview (video or animation), then collapses. Transition to a digital museum – auto-advance rooms (ancient, modern, future) with spotlight captions and Ken Burns pans. Crossfade art pieces with ambient motion and title overlays.",
    "Create a futuristic animated game demo system in English only. Desktop and mobile compatible. After a 5s intro, autoplay a 25s zero-click scripted demo (~30s total). Vanilla JS only, same HTML file. Auto-navigate menus (Start, Options, Credits), then launch a demo level. Use scripted inputs to move a character left/right, shoot projectiles, and score points on screen. Show a short arcade sequence with moving enemies, collision flashes, and a final score tally. All without user interaction.",
    "Create a futuristic animated timeline & weather lab in English only. Desktop and mobile compatible. After a 5s intro, autoplay a 25s zero-click scripted demo (~30s total). Vanilla JS only, same HTML file. Auto-scroll through history eras (1920, 1980, 2050) – each highlights events with motion icons. Then switch to a weather visualization: map with storm time-lapse, animated radar, temperature graph updating. Finally run a virtual experiment: pour liquid into a beaker, heat it, measure results with a moving gauge and real-time graph.",
]
PROMPT_STATE_FILE = BASE_DIR / "prompt_state.json"

HTML_BLOCK_RE = re.compile(r"```html\s*([\s\S]*?)```", re.IGNORECASE)
FULL_HTML_RE = re.compile(r"<!doctype html[\s\S]*</html>|<html[\s\S]*</html>", re.IGNORECASE)

_live_lock = threading.Lock()
_gen_started = False
LIVE: dict[str, Any] = {
    "cycle": 0,
    "model": MODEL,
    "generating": False,
    "promptIndex": -1,
    "prompt": "",
    "thinking": "",
    "text": "",
    "startedAtMs": 0,
    "firstTokenMs": None,
    "doneAtMs": 0,
    "phase": "boot",
    "nextAtMs": 0,
    "lastSaved": "",
    "lastError": "",
}


def _now_ms() -> int:
    return int(time.time() * 1000)

_CPU_NAME_CACHE: str | None = None


def _cpu_name() -> str:
    """Return the marketing CPU name (e.g. Intel Xeon E5-2680 v4)."""
    global _CPU_NAME_CACHE
    if _CPU_NAME_CACHE is not None:
        return _CPU_NAME_CACHE

    name = ""
    try:
        import winreg  # type: ignore[import-not-found]

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        name = str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
    except Exception:
        name = platform.processor() or "CPU"

    _CPU_NAME_CACHE = name or "CPU"
    return _CPU_NAME_CACHE


def _gpu_stats() -> dict[str, Any]:
    """Query the NVIDIA GPU via nvidia-smi. Returns ok=False if unavailable."""
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        if out.returncode == 0 and out.stdout.strip():
            line = out.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in line.split(",")]
            name, util, mem_used, mem_total, temp = parts[:5]
            mem_total_f = float(mem_total) or 1.0
            return {
                "ok": True,
                "name": name,
                "util": float(util),
                "memUsed": float(mem_used),
                "memTotal": float(mem_total),
                "memPct": round(float(mem_used) / mem_total_f * 100, 1),
                "temp": float(temp),
            }
    except Exception as exc:  # pragma: no cover - hardware/driver dependent
        return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "nvidia-smi unavailable"}


def _system_stats() -> dict[str, Any]:
    """Collect live CPU / RAM / GPU telemetry."""
    cpu: dict[str, Any]
    ram: dict[str, Any]
    if psutil is not None:
        vm = psutil.virtual_memory()
        cpu = {
            "name": _cpu_name(),
            "percent": psutil.cpu_percent(interval=None),
            "cores": psutil.cpu_count(logical=True),
            "physical": psutil.cpu_count(logical=False),
        }
        ram = {
            "percent": vm.percent,
            "usedGb": round(vm.used / (1024 ** 3), 1),
            "totalGb": round(vm.total / (1024 ** 3), 1),
        }
    else:
        cpu = {"name": _cpu_name(), "percent": 0, "cores": 0, "physical": 0}
        ram = {"percent": 0, "usedGb": 0, "totalGb": 0}

    return {
        "cpu": cpu,
        "ram": ram,
        "gpu": _gpu_stats(),
        "ts": datetime.now().isoformat(),
    }


def _read_json(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8-sig"))


def _wav_tone(
    frequency: float = 440.0,
    duration_sec: float = 0.15,
    volume: float = 0.55,
    *,
    noise: bool = False,
    sample_rate: int = 22050,
) -> bytes:
    """Generate a short PCM WAV for browser SFX (no Web Audio required)."""
    n_samples = max(1, int(duration_sec * sample_rate))
    attack = max(1, int(sample_rate * 0.006))
    release = max(1, int(sample_rate * 0.04))
    pcm = bytearray()
    for i in range(n_samples):
        env = 1.0
        if i < attack:
            env = i / attack
        elif i > n_samples - release:
            env = max(0.0, (n_samples - i) / release)
        if noise:
            sample = (random.random() * 2.0 - 1.0) * volume * env
        else:
            t = i / sample_rate
            sample = math.sin(2.0 * math.pi * frequency * t) * volume * env
        pcm.extend(struct.pack("<h", int(max(-32767, min(32767, sample * 32767)))))
    data_size = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        sample_rate,
        sample_rate * 2,
        2,
        16,
        b"data",
        data_size,
    )
    return header + bytes(pcm)


_PRIME_WAV = _wav_tone(60.0, 1.2, 0.02)


def _binary_response(
    handler: SimpleHTTPRequestHandler, data: bytes, content_type: str, *, cache: str = "no-store"
) -> None:
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", cache)
    handler.end_headers()
    handler.wfile.write(data)


def _json_response(handler: SimpleHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def _ensure_archive_dir() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def _archive_public_name(filename: str) -> str:
    """URL path relative to BASE_DIR (e.g. archive/index-4.7-VER12.html)."""
    return f"{ARCHIVE_URL_PREFIX}/{filename}"


def _migrate_legacy_archive_files() -> None:
    """Move model creations from project root into archive/ (one-time per file)."""
    _ensure_archive_dir()
    for pattern in ("index-4.7-VER*.html", "index-4.7-VER*.json"):
        for file in BASE_DIR.glob(pattern):
            dest = ARCHIVE_DIR / file.name
            if dest.exists():
                continue
            try:
                file.rename(dest)
            except OSError as exc:
                print(f"[broadcast_server] Could not move {file.name} to archive: {exc}")


def _next_ver_filename() -> str:
    _ensure_archive_dir()
    highest = 0
    for file in ARCHIVE_DIR.glob("index-4.7-VER*.html"):
        m = VER_FILE_RE.match(file.name)
        if not m:
            continue
        highest = max(highest, int(m.group(1)))
    return f"index-4.7-VER{highest + 1}.html"


def _list_creation_files() -> list[dict[str, Any]]:
    _ensure_archive_dir()
    items: list[dict[str, Any]] = []
    for file in ARCHIVE_DIR.glob("index-4.7-VER*.html"):
        if file.stat().st_size < 30:
            continue
        items.append(
            {
                "name": file.relative_to(BASE_DIR).as_posix(),
                "size": file.stat().st_size,
                "modified": datetime.fromtimestamp(file.stat().st_mtime).isoformat(),
            }
        )
    items.sort(key=lambda i: i["modified"], reverse=True)
    return items


def _extract_html(raw: str) -> str:
    """Pull a standalone HTML document out of the raw model output."""
    if not raw:
        return ""
    block = HTML_BLOCK_RE.search(raw)
    if block and block.group(1).strip():
        return block.group(1).strip()
    full = FULL_HTML_RE.search(raw)
    if full and full.group(0).strip():
        return full.group(0).strip()
    escaped = raw.replace("&", "&amp;").replace("<", "&lt;")
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0"></head>'
        '<body style="margin:0;background:#02070c;color:#dff;display:flex;align-items:center;'
        'justify-content:center;min-height:100vh;font-family:Segoe UI,sans-serif;">'
        '<pre style="white-space:pre-wrap;max-width:90vw;max-height:90vh;overflow:auto;">'
        f"{escaped}</pre></body></html>"
    )


def _save_creation_html(html: str, model: str, cycle: Any) -> str:
    """Persist an HTML creation under archive/. Returns public path for APIs/UI."""
    _ensure_archive_dir()
    filename = _next_ver_filename()
    output_path = ARCHIVE_DIR / filename
    output_path.write_text(html, encoding="utf-8")
    metadata = {
        "savedAt": datetime.now().isoformat(),
        "model": str(model),
        "cycle": cycle,
        "chars": len(html),
    }
    output_path.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return _archive_public_name(filename)


def _read_prompt_index() -> int:
    """Return the index of the LAST used prompt (-1 if none yet)."""
    try:
        if PROMPT_STATE_FILE.exists():
            data = json.loads(PROMPT_STATE_FILE.read_text(encoding="utf-8-sig"))
            return int(data.get("lastIndex", -1))
    except Exception:
        pass
    return -1


def _advance_prompt() -> tuple[int, str]:
    """Pick the NEXT prompt in rotation and persist the new position to disk."""
    last = _read_prompt_index()
    idx = (last + 1) % len(PROMPTS)
    prompt = PROMPTS[idx]
    try:
        PROMPT_STATE_FILE.write_text(
            json.dumps(
                {
                    "lastIndex": idx,
                    "total": len(PROMPTS),
                    "lastPrompt": prompt,
                    "updatedAt": datetime.now().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    return idx, prompt


def _stream_once(model: str, prompt: str) -> None:
    """Stream a single generation from Ollama into the shared LIVE buffer."""
    if requests is None:
        raise RuntimeError("python 'requests' package not installed")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "think": True,  # capture the model's reasoning/thinking phase too
        "options": {"temperature": 1.0, "top_p": 0.95},
    }
    with requests.post(OLLAMA_URL, json=payload, stream=True, timeout=(10, None)) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:160]}")
        with _live_lock:
            LIVE["model"] = model
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            thinking = obj.get("thinking")
            token = obj.get("response")
            if thinking:
                with _live_lock:
                    if LIVE["firstTokenMs"] is None:
                        LIVE["firstTokenMs"] = _now_ms() - LIVE["startedAtMs"]
                    LIVE["thinking"] += thinking
            if token:
                with _live_lock:
                    if LIVE["firstTokenMs"] is None:
                        LIVE["firstTokenMs"] = _now_ms() - LIVE["startedAtMs"]
                    LIVE["text"] += token
            if obj.get("done"):
                break


def _generation_loop() -> None:
    """Single-owner loop: continuously generate, stream to LIVE, and archive."""
    while True:
        prompt_index, prompt = _advance_prompt()
        with _live_lock:
            LIVE["cycle"] += 1
            LIVE["generating"] = True
            LIVE["promptIndex"] = prompt_index
            LIVE["prompt"] = prompt
            LIVE["thinking"] = ""
            LIVE["text"] = ""
            LIVE["startedAtMs"] = _now_ms()
            LIVE["firstTokenMs"] = None
            LIVE["phase"] = "generating"
            LIVE["lastError"] = ""
            cycle = LIVE["cycle"]

        ok = False
        for model in (MODEL, FALLBACK_MODEL):
            try:
                _stream_once(model, prompt)
                ok = True
                break
            except Exception as exc:  # pragma: no cover - network/model dependent
                with _live_lock:
                    LIVE["lastError"] = f"{model}: {exc}"
                time.sleep(1.5)
                continue

        with _live_lock:
            text = LIVE["text"]
            model_used = LIVE["model"]
            LIVE["generating"] = False
            LIVE["doneAtMs"] = _now_ms()

        if ok and len(text.strip()) >= 30:
            try:
                fname = _save_creation_html(_extract_html(text), model_used, cycle)
                with _live_lock:
                    LIVE["lastSaved"] = fname
            except Exception as exc:  # pragma: no cover
                with _live_lock:
                    LIVE["lastError"] = f"save: {exc}"

        with _live_lock:
            LIVE["phase"] = "cooldown"
            LIVE["nextAtMs"] = _now_ms() + COOLDOWN_MS
        time.sleep(COOLDOWN_MS / 1000)


def _start_generation_engine() -> None:
    global _gen_started
    if _gen_started:
        return
    _gen_started = True
    threading.Thread(target=_generation_loop, name="ollama-gen", daemon=True).start()


def _live_snapshot(since: int) -> dict[str, Any]:
    """Return current generation state + delta of the conversation since `since` chars."""
    with _live_lock:
        think = LIVE["thinking"]
        resp = LIVE["text"]
        # Build the on-screen conversation: reasoning phase first, then the output
        if think:
            display = "\u25B8 REASONING\n" + think
            if resp:
                display += "\n\n\u25B8 OUTPUT\n" + resp
        else:
            display = resp
        reasoning = bool(think) and not resp
        chars = len(display)
        reset = since < 0 or since > chars
        append = display if reset else display[since:]
        if LIVE["generating"]:
            elapsed = _now_ms() - LIVE["startedAtMs"]
        else:
            elapsed = max(0, LIVE["doneAtMs"] - LIVE["startedAtMs"])
        next_in = max(0, LIVE["nextAtMs"] - _now_ms()) if LIVE["phase"] == "cooldown" else 0
        return {
            "ok": True,
            "cycle": LIVE["cycle"],
            "model": LIVE["model"],
            "generating": LIVE["generating"],
            "reasoning": reasoning,
            "prompt": LIVE["prompt"],
            "promptIndex": LIVE["promptIndex"],
            "promptTotal": len(PROMPTS),
            "chars": chars,
            "reset": reset,
            "append": append,
            "startedAtMs": LIVE["startedAtMs"],
            "firstTokenMs": LIVE["firstTokenMs"],
            "elapsedMs": elapsed,
            "phase": LIVE["phase"],
            "nextInMs": next_in,
            "lastSaved": LIVE["lastSaved"],
            "lastError": LIVE["lastError"],
        }


class BroadcastHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Permissions-Policy", "autoplay=(self)")
        super().end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/api/list_creations":
            _json_response(self, {"ok": True, "files": _list_creation_files()})
            return

        if route == "/api/health":
            _json_response(
                self,
                {"ok": True, "baseDir": str(BASE_DIR), "archiveDir": str(ARCHIVE_DIR)},
            )
            return

        if route == "/api/stats":
            try:
                _json_response(self, {"ok": True, "stats": _system_stats()})
            except Exception as exc:  # pragma: no cover
                _json_response(self, {"ok": False, "error": str(exc)}, status=500)
            return

        if route == "/api/live":
            qs = parse_qs(urlparse(self.path).query)
            try:
                since = int(qs.get("since", ["0"])[0])
            except (TypeError, ValueError):
                since = 0
            _json_response(self, _live_snapshot(since))
            return

        if route == "/sfx/prime.wav":
            _binary_response(self, _PRIME_WAV, "audio/wav", cache="public, max-age=3600")
            return

        if route == "/sfx/beep":
            qs = parse_qs(urlparse(self.path).query)
            try:
                freq = float(qs.get("f", ["440"])[0])
                dur = float(qs.get("d", ["0.15"])[0])
                vol = float(qs.get("v", ["0.55"])[0])
            except (TypeError, ValueError):
                freq, dur, vol = 440.0, 0.15, 0.55
            noise = qs.get("n", ["0"])[0] in ("1", "true", "yes")
            freq = max(40.0, min(4000.0, freq))
            dur = max(0.03, min(2.5, dur))
            vol = max(0.05, min(1.0, vol))
            wav = _wav_tone(freq, dur, vol, noise=noise)
            _binary_response(self, wav, "audio/wav", cache="public, max-age=300")
            return

        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route != "/api/save_creation":
            _json_response(self, {"ok": False, "error": "Not found"}, status=404)
            return

        try:
            body = _read_json(self)
        except json.JSONDecodeError:
            _json_response(self, {"ok": False, "error": "Invalid JSON"}, status=400)
            return

        html = str(body.get("html", ""))
        if len(html.strip()) < 30:
            _json_response(self, {"ok": False, "error": "HTML is empty"}, status=400)
            return

        filename = _save_creation_html(html, body.get("model", ""), body.get("cycle"))
        _json_response(
            self,
            {
                "ok": True,
                "filename": filename,
                "metadata": Path(filename).with_suffix(".json").name,
                "chars": len(html),
            },
        )


def main() -> None:
    if psutil is not None:
        psutil.cpu_percent(interval=None)  # prime non-blocking CPU sampling
    _migrate_legacy_archive_files()
    _start_generation_engine()
    server = ThreadingHTTPServer(("", 8000), BroadcastHandler)
    print("[broadcast_server] Serving on http://localhost:8000")
    print(f"[broadcast_server] Base dir: {BASE_DIR}")
    print(f"[broadcast_server] Archive dir: {ARCHIVE_DIR}")
    print("[broadcast_server] Generation engine started (single-owner Ollama stream)")
    server.serve_forever()


if __name__ == "__main__":
    main()
