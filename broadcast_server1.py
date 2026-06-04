#!/usr/bin/env python3
"""Local server for Ollama broadcast channel.
Serves static files and provides JSON APIs for listing/saving creations.
"""

from __future__ import annotations

import json
import platform
import re
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

# Display-only: external tool writes to archive/; this server only serves files + stats.
DISPLAY_ONLY = True

# --- Generation engine config (optional; disabled when DISPLAY_ONLY) ---
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "glm-4.7-flash"
COOLDOWN_MS = 6000
OLLAMA_THINK = True
OLLAMA_NUM_PREDICT = 16384
# Hugging Face zai-org/GLM-4.7-Flash defaults (most tasks)
OLLAMA_TEMPERATURE = 1.0
OLLAMA_TOP_P = 0.95
MIN_HTML_SAVE_CHARS = 2500
OUTPUT_RULES = (
    "CRITICAL: Your answer must be ONE complete, valid HTML document only. "
    "Include <!DOCTYPE html> through </html> with inline CSS and JS. "
    "Do not stop mid-file. Do not output markdown fences unless the full HTML is inside them."
)

# Rotating prompts: edit prompts.json (30 game/auto-demo themes).
# CDN + audio/asset guide: generation_libraries.json (prepended to every Ollama request).
PROMPTS_FILE = BASE_DIR / "prompts.json"
LIBRARIES_FILE = BASE_DIR / "generation_libraries.json"
PROMPT_STATE_FILE = BASE_DIR / "prompt_state.json"

_preamble_cache: str | None = None


def _load_prompts() -> list[str]:
    try:
        data = json.loads(PROMPTS_FILE.read_text(encoding="utf-8-sig"))
        if isinstance(data, list) and data:
            return [str(p).strip() for p in data if str(p).strip()]
    except Exception:
        pass
    return [
        "Create a simple Canvas game in one HTML file with title screen, auto-demo bot, and mobile touch controls."
    ]


def _load_libraries_doc() -> dict[str, Any]:
    try:
        return json.loads(LIBRARIES_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def _library_preamble() -> str:
    global _preamble_cache
    if _preamble_cache is not None:
        return _preamble_cache
    doc = _load_libraries_doc()
    lines = ["=== GENERATION LIBRARIES (use these CDN URLs in your HTML) ==="]
    for rule in doc.get("globalRules", []):
        lines.append(f"- {rule}")
    lines.append("")
    lines.append("CDN scripts:")
    for lib in doc.get("libraries", []):
        name = lib.get("name", lib.get("id", "lib"))
        use = lib.get("use", "")
        script = lib.get("script", "")
        lines.append(f"- {name}: {use} -> {script}")
    audio = doc.get("audioSources", {})
    if audio:
        lines.append("")
        lines.append("Audio SFX sources: " + ", ".join(
            f"{k}={v}" for k, v in audio.items() if k != "note"
        ))
        if audio.get("note"):
            lines.append(str(audio["note"]))
    assets = doc.get("assetSources", {})
    if assets:
        lines.append("Art/sprites: " + ", ".join(f"{k}={v}" for k, v in assets.items()))
    for note in doc.get("uiNotes", []):
        lines.append(f"- {note}")
    lines.append("=== END LIBRARIES ===")
    _preamble_cache = "\n".join(lines)
    return _preamble_cache


def _compose_generation_prompt(task: str) -> str:
    t = task.strip()
    if "no external dependencies" in t.lower():
        rules = (
            "=== RULES ===\n"
            "- ONE complete standalone HTML file (inline CSS + JS). English only.\n"
            "- Must run in browser: valid <!DOCTYPE html> ... </html>, no placeholders.\n"
            "- No CDN, no external scripts. Mobile-first, seamless loop where applicable.\n"
        )
        return f"{rules}\n{OUTPUT_RULES}\n\n=== TASK ===\n{t}"
    return f"{_library_preamble()}\n\n{OUTPUT_RULES}\n\n=== TASK ===\n{t}"


PROMPTS = _load_prompts()

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


def _is_complete_html(html: str) -> bool:
    if not html or len(html) < 200:
        return False
    low = html.lower()
    return ("</html>" in low) and ("<html" in low or "<!doctype" in low)


def _repair_incomplete_html(source: str) -> str:
    """Close truncated model output when <!DOCTYPE or <html> started but </html> missing."""
    if not source or len(source) < 500:
        return ""
    m = re.search(r"(<!DOCTYPE html[\s\S]*|<html[\s\S]*)", source, re.IGNORECASE)
    if not m:
        return ""
    html = source[m.start() :].strip()
    low = html.lower()
    if "</html>" in low:
        return html
    if "</script>" not in low and "<script" in low:
        html += "\n</script>"
    if "</style>" not in low and "<style" in low:
        html += "\n</style>"
    if "</body>" not in low:
        html += "\n</body>"
    html += "\n</html>"
    return html if _is_complete_html(html) else ""


def _extract_html(raw: str, thinking: str = "") -> str:
    """Pull a complete standalone HTML document from model output (never save fragments)."""
    candidates: list[str] = []
    for source in (raw, thinking, f"{raw}\n{thinking}"):
        if not source or not source.strip():
            continue
        for block in HTML_BLOCK_RE.findall(source):
            b = block.strip()
            if b:
                candidates.append(b)
        full = FULL_HTML_RE.search(source)
        if full:
            candidates.append(full.group(0).strip())
    candidates.sort(key=len, reverse=True)
    for html in candidates:
        if _is_complete_html(html):
            return html
    for source in (raw, thinking, f"{raw}\n{thinking}"):
        repaired = _repair_incomplete_html(source)
        if repaired:
            return repaired
    return ""


def _wrap_raw_fallback(raw: str) -> str:
    """Debug view only — not used for archive saves."""
    escaped = raw.replace("&", "&amp;").replace("<", "&lt;")
    return (
        '<!DOCTYPE html><html><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0"></head>'
        '<body style="margin:0;background:#02070c;color:#dff;display:flex;align-items:center;'
        'justify-content:center;min-height:100vh;font-family:Segoe UI,sans-serif;">'
        '<pre style="white-space:pre-wrap;max-width:90vw;max-height:90vh;overflow:auto;">'
        f"{escaped}</pre></body></html>"
    )


def _save_creation_html(
    html: str,
    model: str,
    cycle: Any,
    *,
    prompt: str = "",
    prompt_index: int | None = None,
) -> str:
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
        "prompt": str(prompt or "").strip(),
        "promptIndex": prompt_index,
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
    global PROMPTS, _preamble_cache
    PROMPTS = _load_prompts()
    _preamble_cache = None
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


def _stream_once(
    model: str,
    prompt: str,
    *,
    extra_options: dict[str, Any] | None = None,
    think: bool | None = None,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """Stream a single generation from Ollama into the shared LIVE buffer."""
    if requests is None:
        raise RuntimeError("python 'requests' package not installed")
    options: dict[str, Any] = {
        "temperature": OLLAMA_TEMPERATURE,
        "top_p": OLLAMA_TOP_P,
        "repeat_penalty": 1.05,
        "num_predict": OLLAMA_NUM_PREDICT,
    }
    if extra_options:
        options.update(extra_options)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "think": OLLAMA_THINK if think is None else think,
        "options": options,
    }
    stats: dict[str, Any] = {"eval_count": 0, "thinking_chars": 0, "response_chars": 0}
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
            msg = obj.get("message") or {}
            thinking = msg.get("thinking") or obj.get("thinking")
            token = msg.get("content") or obj.get("response")
            if thinking:
                stats["thinking_chars"] += len(thinking)
                with _live_lock:
                    if LIVE["firstTokenMs"] is None:
                        LIVE["firstTokenMs"] = _now_ms() - LIVE["startedAtMs"]
                    LIVE["thinking"] += thinking
            if token:
                stats["response_chars"] += len(token)
                with _live_lock:
                    if LIVE["firstTokenMs"] is None:
                        LIVE["firstTokenMs"] = _now_ms() - LIVE["startedAtMs"]
                    LIVE["text"] += token
            if on_progress:
                on_progress(stats, LIVE.get("text", ""), LIVE.get("thinking", ""))
            if obj.get("done"):
                stats["eval_count"] = int(obj.get("eval_count") or 0)
                break
    return stats


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
        stream_stats: dict[str, Any] = {}
        try:
            stream_stats = _stream_once(MODEL, _compose_generation_prompt(prompt))
            ok = True
        except Exception as exc:  # pragma: no cover - network/model dependent
            with _live_lock:
                LIVE["lastError"] = f"{MODEL}: {exc}"

        with _live_lock:
            text = LIVE["text"]
            thinking_text = LIVE["thinking"]
            model_used = LIVE["model"]
            prompt_used = LIVE["prompt"]
            prompt_index_used = LIVE["promptIndex"]
            LIVE["generating"] = False
            LIVE["doneAtMs"] = _now_ms()

        html = _extract_html(text, thinking_text)
        if ok and _is_complete_html(html) and len(html) >= MIN_HTML_SAVE_CHARS:
            try:
                fname = _save_creation_html(
                    html,
                    model_used,
                    cycle,
                    prompt=prompt_used,
                    prompt_index=prompt_index_used,
                )
                with _live_lock:
                    LIVE["lastSaved"] = fname
                    LIVE["lastError"] = ""
            except Exception as exc:  # pragma: no cover
                with _live_lock:
                    LIVE["lastError"] = f"save: {exc}"
        elif ok:
            with _live_lock:
                LIVE["lastError"] = (
                    f"incomplete HTML (extracted {len(html)} chars, "
                    f"response {len(text)}, thinking {len(thinking_text)}, "
                    f"eval_count {stream_stats.get('eval_count', '?')}, think={OLLAMA_THINK})"
                )
                LIVE["lastSaved"] = ""

        with _live_lock:
            LIVE["phase"] = "cooldown"
            LIVE["nextAtMs"] = _now_ms() + COOLDOWN_MS
        time.sleep(COOLDOWN_MS / 1000)


def _ollama_probe() -> dict[str, Any]:
    """Quick health check for Ollama model resolution and think/response split."""
    if requests is None:
        return {"ok": False, "error": "requests not installed"}
    test_prompt = "Return exactly: PING_OK"
    out: dict[str, Any] = {
        "ok": False,
        "ollamaUrl": OLLAMA_URL,
        "thinkEnabled": OLLAMA_THINK,
        "numPredict": OLLAMA_NUM_PREDICT,
        "models": {},
    }
    row: dict[str, Any] = {"model": MODEL}
    for think_flag in (False, True):
        key = f"think_{think_flag}"
        payload = {
            "model": MODEL,
            "messages": [{"role": "user", "content": test_prompt}],
            "stream": False,
            "think": think_flag,
            "options": {
                "num_predict": 64,
                "temperature": OLLAMA_TEMPERATURE,
                "top_p": OLLAMA_TOP_P,
            },
        }
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=120)
            row[key] = {
                "status": r.status_code,
                "responseLen": 0,
                "thinkingLen": 0,
            }
            if r.status_code == 200:
                data = r.json()
                msg = data.get("message") or {}
                content = msg.get("content") or data.get("response") or ""
                thinking = msg.get("thinking") or data.get("thinking") or ""
                row[key]["responseLen"] = len(content)
                row[key]["thinkingLen"] = len(thinking)
                row[key]["evalCount"] = data.get("eval_count")
                row[key]["responsePreview"] = content[:80]
            else:
                row[key]["error"] = r.text[:200]
        except Exception as exc:
            row[key] = {"error": str(exc)}
    out["models"]["primary"] = row
    if row.get("think_False", {}).get("status") == 200:
        out["ok"] = True
    return out


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
                {
                    "ok": True,
                    "baseDir": str(BASE_DIR),
                    "archiveDir": str(ARCHIVE_DIR),
                    "displayOnly": DISPLAY_ONLY,
                    "archiveCount": len(_list_creation_files()),
                },
            )
            return

        if route == "/api/stats":
            try:
                _json_response(self, {"ok": True, "stats": _system_stats()})
            except Exception as exc:  # pragma: no cover
                _json_response(self, {"ok": False, "error": str(exc)}, status=500)
            return

        if route == "/api/live":
            if DISPLAY_ONLY:
                _json_response(
                    self,
                    {
                        "ok": True,
                        "displayOnly": True,
                        "generating": True,
                        "model": "ARCHIVE SIMULATION",
                        "phase": "display",
                        "append": "",
                        "reset": True,
                        "chars": 0,
                    },
                )
                return
            qs = parse_qs(urlparse(self.path).query)
            try:
                since = int(qs.get("since", ["0"])[0])
            except (TypeError, ValueError):
                since = 0
            _json_response(self, _live_snapshot(since))
            return

        if route == "/api/ollama_probe":
            try:
                _json_response(self, _ollama_probe())
            except Exception as exc:  # pragma: no cover
                _json_response(self, {"ok": False, "error": str(exc)}, status=500)
            return

        if route == "/api/generation_libraries":
            doc = _load_libraries_doc()
            _json_response(
                self,
                {
                    "ok": True,
                    "promptCount": len(_load_prompts()),
                    "libraries": doc,
                    "preamblePreview": _library_preamble()[:2000],
                },
            )
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
    server = ThreadingHTTPServer(("", 8000), BroadcastHandler)
    print("[broadcast_server] Serving on http://localhost:8000")
    print(f"[broadcast_server] Base dir: {BASE_DIR}")
    print(f"[broadcast_server] Archive dir: {ARCHIVE_DIR}")
    if DISPLAY_ONLY:
        n = len(_list_creation_files())
        print(f"[broadcast_server] DISPLAY-ONLY mode ({n} archive HTML files, no Ollama loop)")
    else:
        _start_generation_engine()
        print("[broadcast_server] Generation engine started (single-owner Ollama stream)")
    server.serve_forever()


if __name__ == "__main__":
    main()
