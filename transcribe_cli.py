#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import atexit
import ctypes
import glob
import json
import os
import re
import shutil
import site
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

import setup_env

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTDIR = os.path.join(SCRIPT_DIR, "salidas")
DEFAULT_MODEL = "auto"
FALLBACK_MODEL = "small"
KEY_FILES = [
    os.path.join(SCRIPT_DIR, "deepgram.key"),
    os.path.expanduser("~/.hermes/deepgram.key"),
]
MEDIA_EXT = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v",
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".wma", ".amr",
}

PRESETS = {
    "fast": {"beam_size": 1, "temperature": 0.0, "compute_cuda": "int8_float16", "compute_cpu": "int8"},
    "balanced": {"beam_size": 2, "temperature": 0.0, "compute_cuda": "int8_float16", "compute_cpu": "int8"},
    "quality": {"beam_size": 5, "temperature": [0.0, 0.2, 0.4], "compute_cuda": "float16", "compute_cpu": "int8"},
}

# Colores ANSI (compatibles con Windows 10/11 y WSL)
C_RESET = "\033[0m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_MAGENTA = "\033[95m"
C_RED = "\033[91m"
C_DIM = "\033[90m"
C_BOLD = "\033[1m"

KAOMOJI_WORK = ["( •̀ᴗ•́ )و", "( ˘▽˘)っ♪", "(ง •̀_•́)ง", "ヾ(⌐■_■)ノ♪"]
KAOMOJI_LOAD = "(づ｡◕‿‿◕｡)づ"
KAOMOJI_SHRUG = r"¯\_(ツ)_/¯"
KAOMOJI_SAVE = "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧"
KAOMOJI_DONE = r"\(•◡•)/"
KAOMOJI_ERR = "(╯°□°）╯︵ ┻━┻"

_ACTIVE_TEMP_DIRS: set[str] = set()


def _cleanup_temps() -> None:
    for d in list(_ACTIVE_TEMP_DIRS):
        shutil.rmtree(d, ignore_errors=True)
        _ACTIVE_TEMP_DIRS.discard(d)


atexit.register(_cleanup_temps)


def log(msg: str, kaomoji: str = "", color: str = "") -> None:
    prefix = f"{C_DIM}[{time.strftime('%H:%M:%S')}]{C_RESET} "
    k = f"{C_MAGENTA}{kaomoji}{C_RESET} " if kaomoji else ""
    body = f"{color}{msg}{C_RESET}" if color else msg
    print(f"{prefix}{k}{body}", flush=True)


def render_bar(pct: float, frame_idx: int, extra: str = "", queue_tag: str = "") -> None:
    pct = max(0.0, min(100.0, pct))
    width = 22
    filled = int(round(width * pct / 100.0))
    bar = "█" * filled + "░" * (width - filled)
    kao = KAOMOJI_WORK[frame_idx % len(KAOMOJI_WORK)]
    q = f"{C_YELLOW}{queue_tag}{C_RESET} " if queue_tag else ""
    line = f"\r\033[K{C_MAGENTA}{kao}{C_RESET} {q}{C_CYAN}[{bar}]{C_RESET} {C_BOLD}{pct:5.1f}%{C_RESET} {C_DIM}{extra}{C_RESET}"
    sys.stdout.write(line)
    sys.stdout.flush()


def finish_bar(extra: str = "", queue_tag: str = "") -> None:
    width = 22
    bar = "█" * width
    q = f"{C_YELLOW}{queue_tag}{C_RESET} " if queue_tag else ""
    line = f"\r\033[K{C_GREEN}{KAOMOJI_DONE}{C_RESET} {q}{C_GREEN}[{bar}]{C_RESET} {C_BOLD}100.0%{C_RESET} {C_DIM}{extra}{C_RESET}\n"
    sys.stdout.write(line)
    sys.stdout.flush()


def win_to_wsl(path: str) -> str:
    p = path.strip().strip('"').strip("'")
    if p.startswith("file:///"):
        p = urllib.parse.unquote(p[8:] if os.name == "nt" else p[7:])
    if os.name == "nt":
        return os.path.normpath(p)
    if re.match(r"^[A-Za-z]:[\\/]", p):
        return f"/mnt/{p[0].lower()}" + p[2:].replace("\\", "/")
    return p.replace("\\", "/")


def open_folder_for_user(folder_path: str) -> None:
    """Abre automaticamente la carpeta de resultados en el Explorador de Windows para comodidad del usuario."""
    try:
        if os.name == "nt":
            os.startfile(folder_path)  # type: ignore[attr-defined]
        elif shutil.which("explorer.exe"):
            m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", folder_path)
            if m:
                win_p = f"{m.group(1).upper()}:\\" + m.group(2).replace("/", "\\")
                subprocess.Popen(["explorer.exe", win_p], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def preload_nvidia_libs() -> None:
    """Carga cublas/cudnn desde site-packages en Linux/WSL o Windows."""
    roots = []
    try:
        roots.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        roots.append(site.getusersitepackages())
    except Exception:
        pass
    if os.name != "nt":
        roots.extend(glob.glob(os.path.expanduser("~/.local/lib/python*/site-packages")))

    if os.name == "nt":
        for root in dict.fromkeys(roots):
            for sub in ("nvidia\\cublas\\bin", "nvidia\\cudnn\\bin", "nvidia\\cuda_runtime\\bin"):
                d = os.path.join(root, sub)
                if os.path.isdir(d):
                    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                    if hasattr(os, "add_dll_directory"):
                        try:
                            os.add_dll_directory(d)
                        except OSError:
                            pass
        return

    lib_dirs: list[str] = []
    for root in dict.fromkeys(roots):
        for sub in ("nvidia/cublas/lib", "nvidia/cudnn/lib", "nvidia/cuda_runtime/lib"):
            d = os.path.join(root, sub)
            if os.path.isdir(d):
                lib_dirs.append(d)

    if lib_dirs:
        cur = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([cur] if cur else []))
        for d in lib_dirs:
            for pattern in ("libcublas*.so*", "libcublasLt*.so*", "libcudnn*.so*"):
                for so in sorted(glob.glob(os.path.join(d, pattern))):
                    try:
                        ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass


def query_nvidia_gpus() -> list[dict]:
    return setup_env.get_nvidia_gpus()


def free_ram_mb() -> int:
    _, avail = setup_env.get_ram_info_mb()
    return avail


def cuda_is_ready() -> tuple[bool, str]:
    preload_nvidia_libs()
    try:
        import ctranslate2
        cnt = ctranslate2.get_cuda_device_count()
        if cnt <= 0:
            return False, "sin CUDA"
        return True, f"{cnt} GPU detectada(s)"
    except Exception as e:
        return False, f"CUDA no disponible ({e})"


def resolve_igpu_backend(args) -> tuple[str | None, str | None]:
    candidates = [args.igpu_bin, os.environ.get("WHISPER_IGPU_BIN", ""), "whisper-cli", "whisper-vulkan"]
    for c in candidates:
        if c and shutil.which(c):
            return "whispercpp", shutil.which(c)
    try:
        import openvino  # noqa: F401
        import openvino_genai  # noqa: F401
        return "openvino", "openvino_genai"
    except Exception:
        pass
    return None, None


def choose_cuda_params(free_mb: int, preset_cfg: dict, args) -> tuple[str, int]:
    ctype = args.compute_type or preset_cfg["compute_cuda"]
    if free_mb < 1800 and ctype == "float16":
        ctype = "int8_float16"
    if free_mb < 1200:
        ctype = "int8"

    if args.batch_size > 0:
        batch = args.batch_size
    elif free_mb >= 4500:
        batch = 16
    elif free_mb >= 2500:
        batch = 8
    elif free_mb >= 1400:
        batch = 4
    else:
        batch = 2
    return ctype, batch


def find_deepgram_key() -> str | None:
    key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
    if key:
        return key
    for f in KEY_FILES:
        try:
            with open(f, encoding="utf-8") as fh:
                k = fh.read().strip().splitlines()[0].strip()
            if k:
                return k
        except Exception:
            continue
    return None


def hhmmss(t: float, sep: str = ".") -> str:
    t = max(0.0, float(t))
    h, rem = divmod(int(t), 3600)
    m, s = divmod(rem, 60)
    ms = int(round((t - int(t)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def resolve_ffmpeg() -> str | None:
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return exe
    except Exception:
        pass
    return None


def media_duration(path: str) -> float:
    if path.lower().endswith(".wav"):
        try:
            with wave.open(path, "rb") as w:
                frames = w.getnframes()
                rate = w.getframerate()
                if rate > 0:
                    return frames / float(rate)
        except Exception:
            pass
    if shutil.which("ffprobe"):
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", path],
                capture_output=True, text=True, check=True,
            )
            return float(r.stdout.strip())
        except Exception:
            pass
    return 0.0


def is_wav_16k_mono(path: str) -> bool:
    if not path.lower().endswith(".wav"):
        return False
    try:
        with wave.open(path, "rb") as w:
            return w.getnchannels() == 1 and w.getframerate() == 16000 and w.getsampwidth() == 2
    except Exception:
        return False


def to_media_wav(src: str, workdir: str) -> str:
    ffmpeg_bin = resolve_ffmpeg()
    if not ffmpeg_bin:
        raise RuntimeError("Falta el lector de audio/video (ffmpeg). Se reparara en el proximo inicio.")
    if os.path.getsize(src) == 0:
        raise RuntimeError(f"El archivo esta vacio (0 bytes): {os.path.basename(src)}")
    if is_wav_16k_mono(src):
        log("Audio listo para procesar", KAOMOJI_LOAD, C_CYAN)
        return src
    out = os.path.join(workdir, "audio16k.wav")
    cmd = [
        ffmpeg_bin, "-nostdin", "-v", "error", "-y", "-threads", "0",
        "-i", src, "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out,
    ]
    t0 = time.time()
    log("Preparando el audio del archivo...", "(っ'-')╮=͟͟͞͞♪", C_CYAN)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(out) or os.path.getsize(out) < 100:
        raise RuntimeError(f"Este archivo no contiene audio valido o esta danado: '{os.path.basename(src)}'")
    dur = media_duration(out)
    log(f"Audio preparado ({dur/60:.1f} min) en {time.time()-t0:.1f}s", KAOMOJI_SAVE, C_GREEN)
    return out


def resolve_local_model(requested: str) -> tuple[str, str]:
    """
    Devuelve (model_dir_path, friendly_model_name).
    Busca primero cualquier modelo ya existente en la maquina (.hermes, cache HF, o carpeta modelos/)
    para no volver a descargar nunca si ya existe uno.
    """
    installed = setup_env.get_installed_models()

    if requested and requested != "auto":
        if os.path.isdir(requested) and os.path.isfile(os.path.join(requested, "model.bin")):
            return requested, setup_env._normalize_model_name(requested)
        if requested in installed:
            return installed[requested], requested
        local_cand = os.path.join(setup_env.MODELS_DIR, requested)
        if os.path.isfile(os.path.join(local_cand, "model.bin")):
            return local_cand, requested
        return requested, requested

    cfg = setup_env.load_config()
    cfg_path = cfg.get("model_path", "")
    if cfg_path:
        abs_path = cfg_path if os.path.isabs(cfg_path) else os.path.join(SCRIPT_DIR, cfg_path)
        if os.path.isfile(os.path.join(abs_path, "model.bin")):
            return abs_path, cfg.get("model_name") or setup_env._normalize_model_name(abs_path)

    if installed:
        hw = setup_env.inspect_hardware()
        best = setup_env.pick_best_existing_model(installed, hw)
        if best:
            return best[1], best[0]

    log("Configurando el modelo ideal para tu computadora...", KAOMOJI_LOAD, C_YELLOW)
    new_cfg = setup_env.run_setup(auto_accept=False, force_select=False)
    rel = new_cfg.get("model_path", "")
    abs_path = rel if os.path.isabs(rel) else os.path.join(SCRIPT_DIR, rel)
    if os.path.isfile(os.path.join(abs_path, "model.bin")):
        return abs_path, new_cfg.get("model_name", FALLBACK_MODEL)
    return FALLBACK_MODEL, FALLBACK_MODEL


def run_faster_whisper(wav: str, device: str, compute_type: str, batch_size: int,
                       beam_size: int, temperature, threads: int, args, log_path: str,
                       queue_tag: str) -> tuple[list[dict], dict]:
    from faster_whisper import WhisperModel, BatchedInferencePipeline

    model_ref, friendly_name = resolve_local_model(args.model)
    modo_hw = "Tarjeta de Video (GPU)" if device == "cuda" else "Procesador (CPU)"

    t0 = time.time()
    log(f"Iniciando IA ({friendly_name}) usando {modo_hw}...", KAOMOJI_LOAD, C_CYAN)
    model = WhisperModel(model_ref, device=device, compute_type=compute_type, cpu_threads=threads)
    log(f"IA lista en {time.time()-t0:.1f}s -> transcribiendo audio...", KAOMOJI_WORK[0], C_GREEN)

    pipe = BatchedInferencePipeline(model=model)
    segments, info = pipe.transcribe(
        wav,
        language=None if args.detect_language else args.lang,
        batch_size=batch_size,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=300, speech_pad_ms=150),
        condition_on_previous_text=False,
        temperature=temperature,
    )
    total_dur = float(info.duration or 0.0)
    log(f"Idioma detectado: {info.language} | Duracion total: {total_dur/60:.1f} min",
        KAOMOJI_WORK[1], C_CYAN)

    out: list[dict] = []
    n = 0
    render_bar(0.0, 0, f"0.0/{total_dur/60:.1f} min", queue_tag)
    with open(log_path, "w", encoding="utf-8") as fh:
        for seg in segments:
            txt = seg.text.strip()
            if not txt:
                continue
            rec = {"i": n, "start": round(seg.start, 2), "end": round(seg.end, 2), "text": txt}
            out.append(rec)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            pct = (seg.end / total_dur * 100.0) if total_dur > 0 else 0.0
            elapsed = time.time() - t0
            render_bar(pct, n, f"{seg.end/60:.1f}/{total_dur/60:.1f}m | {n} frases | {elapsed:.0f}s", queue_tag)
    finish_bar(f"{total_dur/60:.1f}m | {n} frases | {time.time()-t0:.1f}s", queue_tag)

    meta = {
        "backend": f"local-{device}",
        "model": friendly_name,
        "language": info.language,
        "duration": total_dur,
        "device": device,
        "compute_type": compute_type,
    }
    return out, meta


def run_whispercpp_igpu(wav: str, bin_path: str, args) -> tuple[list[dict], dict]:
    if not args.igpu_model or not os.path.isfile(args.igpu_model):
        raise RuntimeError("Falta --igpu-model para iGPU")
    out_prefix = wav + ".igpu"
    cmd = [
        bin_path, "-m", args.igpu_model, "-f", wav,
        "-l", "auto" if args.detect_language else args.lang,
        "-oj", "-of", out_prefix,
    ]
    t0 = time.time()
    subprocess.run(cmd, check=True)
    with open(out_prefix + ".json", encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for i, item in enumerate(data.get("transcription", [])):
        off = item.get("offsets", {})
        txt = (item.get("text") or "").strip()
        if txt:
            out.append({
                "i": i,
                "start": round(off.get("from", 0) / 1000.0, 2),
                "end": round(off.get("to", 0) / 1000.0, 2),
                "text": txt,
            })
    log(f"GPU integrada lista en {time.time()-t0:.1f}s", KAOMOJI_DONE, C_GREEN)
    return out, {"backend": "local-igpu", "model": args.igpu_model, "language": args.lang,
                 "device": "igpu", "compute_type": "vulkan/opencl"}


def transcribe_local(wav: str, args, log_path: str, queue_tag: str) -> tuple[list[dict], dict]:
    preset_cfg = PRESETS[args.preset]
    beam_size = args.beam_size if args.beam_size > 0 else preset_cfg["beam_size"]
    temperature = preset_cfg["temperature"]
    threads = args.threads or min(max(4, os.cpu_count() or 4), 12)

    order = {
        "auto": ["cuda", "igpu", "cpu"],
        "cuda": ["cuda"],
        "igpu": ["igpu", "cpu"],
        "cpu": ["cpu"],
    }[args.device]

    last_err: Exception | None = None
    for tier in order:
        if tier == "cuda":
            gpus = query_nvidia_gpus()
            ok, _ = cuda_is_ready()
            if not ok or not gpus:
                continue
            best = max(gpus, key=lambda g: g["free_mb"])
            os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            os.environ["CUDA_VISIBLE_DEVICES"] = best["index"]
            ctype, batch = choose_cuda_params(best["free_mb"], preset_cfg, args)
            log(f"Aceleracion por Tarjeta de Video: {best['name']} ({best['free_mb']} MB libres)",
                KAOMOJI_LOAD, C_GREEN)

            attempts = [(ctype, batch)]
            if batch > 2 or ctype != "int8":
                attempts.append(("int8", max(1, min(batch // 2, 4))))
                attempts.append(("int8", 1))

            for try_ctype, try_batch in attempts:
                try:
                    return run_faster_whisper(wav, "cuda", try_ctype, try_batch, beam_size,
                                              temperature, threads, args, log_path, queue_tag)
                except Exception as e:
                    last_err = e
                    log("Ajustando memoria de tarjeta de video automaticamente...", KAOMOJI_SHRUG, C_YELLOW)
            log("Cambiando automaticamente a modo Procesador (CPU) para terminar el trabajo...", KAOMOJI_SHRUG, C_YELLOW)
            continue

        if tier == "igpu":
            kind, target = resolve_igpu_backend(args)
            if kind == "whispercpp" and target and args.igpu_model:
                try:
                    return run_whispercpp_igpu(wav, target, args)
                except Exception as e:
                    last_err = e
                    continue
            continue

        if tier == "cpu":
            ram_mb = free_ram_mb()
            ctype = args.compute_type or preset_cfg["compute_cpu"]
            if ctype in ("float16", "int8_float16"):
                ctype = "int8"
            batch = args.batch_size if args.batch_size > 0 else (4 if ram_mb >= 4096 else 2)
            log(f"Modo Procesador (CPU) optimizado activo ({threads} hilos, {ram_mb // 1024} GB RAM libre)",
                KAOMOJI_WORK[2], C_CYAN)
            try:
                return run_faster_whisper(wav, "cpu", ctype, batch, beam_size, temperature,
                                          threads, args, log_path, queue_tag)
            except Exception as e:
                last_err = e
                if batch > 1:
                    log("Ajustando memoria RAM para equipos ligeros...", KAOMOJI_SHRUG, C_YELLOW)
                    return run_faster_whisper(wav, "cpu", "int8", 1, 1, temperature,
                                              threads, args, log_path, queue_tag)
                raise

    raise RuntimeError(f"No se pudo completar la transcripcion ({last_err})")


def transcribe_deepgram(src: str, args, key: str, log_path: str) -> tuple[list[dict], dict]:
    params = {
        "model": args.dg_model,
        "language": args.lang,
        "smart_format": "true",
        "punctuate": "true",
        "paragraphs": "true",
        "diarize": "true" if args.diarize else "false",
    }
    url = "https://api.deepgram.com/v1/listen?" + urllib.parse.urlencode(params)
    size = os.path.getsize(src)
    log(f"Deepgram: subiendo {size/1e6:.1f} MB...", KAOMOJI_LOAD, C_CYAN)
    req = urllib.request.Request(url, data=None, method="POST")
    with open(src, "rb") as fh:
        req.data = fh.read()
    req.add_header("Authorization", f"Token {key}")
    req.add_header("Content-Type", "application/octet-stream")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=3600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Deepgram HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")
    log(f"Respuesta Deepgram en {time.time()-t0:.0f}s", KAOMOJI_DONE, C_GREEN)

    alt = data["results"]["channels"][0]["alternatives"][0]
    words = alt.get("words") or []
    segs: list[dict] = []
    cur: list[dict] = []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > 1.2 or w["start"] - cur[0]["start"] > 20):
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)

    out: list[dict] = []
    with open(log_path, "w", encoding="utf-8") as fh:
        for i, grp in enumerate(segs):
            txt = " ".join(w.get("punctuated_word") or w["word"] for w in grp).strip()
            spk = grp[0].get("speaker")
            rec = {"i": i, "start": round(grp[0]["start"], 2), "end": round(grp[-1]["end"], 2), "text": txt}
            if spk is not None:
                rec["speaker"] = spk
            out.append(rec)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    meta = {
        "backend": "deepgram",
        "model": args.dg_model,
        "language": args.lang,
        "duration": float(data.get("metadata", {}).get("duration", 0) or 0),
    }
    return out, meta


def split_long(segs: list[dict], max_chars: int = 1100, max_secs: float = 45.0) -> list[dict]:
    out: list[dict] = []
    for r in segs:
        text = r.get("text", "")
        dur = max(0.0, r["end"] - r["start"])
        if len(text) <= max_chars and dur <= max_secs:
            out.append(r)
            continue
        parts = [p for p in re.split(r"(?<=[.?!:])\s+", text) if p]
        chunks, cur, ln = [], [], 0
        for p in parts:
            cur.append(p)
            ln += len(p) + 1
            if ln >= max_chars:
                chunks.append(" ".join(cur))
                cur, ln = [], 0
        if cur:
            chunks.append(" ".join(cur))
        total = max(1, sum(len(c) + 1 for c in chunks))
        pos = 0
        for c in chunks:
            f0 = pos / total
            pos += len(c) + 1
            f1 = min(1.0, pos / total)
            out.append({
                "i": r.get("i"),
                "start": round(r["start"] + dur * f0, 2),
                "end": round(r["start"] + dur * f1, 2),
                "text": c,
            })
    for i, r in enumerate(out):
        r["i"] = i
    return out


def unique_output_path(outdir: str, stem: str, ext: str, overwrite: bool) -> str:
    p = os.path.join(outdir, f"{stem}.{ext}")
    if overwrite or not os.path.exists(p):
        return p
    idx = 1
    while True:
        cand = os.path.join(outdir, f"{stem} ({idx}).{ext}")
        if not os.path.exists(cand):
            return cand
        idx += 1


def write_outputs(segs: list[dict], meta: dict, src: str, outdir: str, stem: str, fmt: str, overwrite: bool) -> list[str]:
    os.makedirs(outdir, exist_ok=True)
    written = []
    segs = split_long(segs)
    want = {"txt", "md", "srt", "jsonl"} if fmt == "all" else {fmt}

    if "jsonl" in want:
        p = unique_output_path(outdir, stem, "jsonl", overwrite)
        with open(p, "w", encoding="utf-8") as fh:
            for r in segs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        written.append(p)

    if "json" in want:
        p = unique_output_path(outdir, stem, "json", overwrite)
        payload = {"source": os.path.basename(src), "meta": meta, "segments": segs}
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        written.append(p)

    if "txt" in want or "md" in want:
        paragraphs = []
        buf, t0, last = [], 0.0, 0.0
        for r in segs:
            if not buf:
                t0 = r["start"]
            buf.append(("[" + (f"P{r['speaker']}] " if r.get("speaker") is not None else "")) + r["text"])
            last = r["end"]
            if last - t0 > 45 or (r["end"] - r["start"] > 30):
                paragraphs.append((hhmmss(t0)[:8], " ".join(buf).strip()))
                buf = []
        if buf:
            paragraphs.append((hhmmss(t0)[:8], " ".join(buf).strip()))

        if "txt" in want:
            p = unique_output_path(outdir, stem, "txt", overwrite)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(f"TRANSCRIPCION: {os.path.basename(src)}\n")
                fh.write(f"motor: {meta.get('backend')} / {meta.get('model')} | idioma: {meta.get('language')}\n")
                fh.write("=" * 70 + "\n\n")
                for ts, txt in paragraphs:
                    fh.write(f"[{ts}] {txt}\n\n")
            written.append(p)

        if "md" in want:
            p = unique_output_path(outdir, stem, "md", overwrite)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(f"# Transcripcion: {os.path.basename(src)}\n\n")
                fh.write(f"- **Motor:** `{meta.get('backend')} / {meta.get('model')}`\n")
                fh.write(f"- **Idioma:** `{meta.get('language')}`\n")
                fh.write(f"- **Duracion:** `{hhmmss(meta.get('duration', 0))[:8]}`\n\n")
                fh.write("---\n\n")
                for ts, txt in paragraphs:
                    fh.write(f"**[{ts}]** {txt}\n\n")
            written.append(p)

    if "srt" in want:
        p = unique_output_path(outdir, stem, "srt", overwrite)
        with open(p, "w", encoding="utf-8") as fh:
            for i, r in enumerate(segs, 1):
                fh.write(f"{i}\n{hhmmss(r['start'], ',')} --> {hhmmss(r['end'], ',')}\n{r['text']}\n\n")
        written.append(p)

    if "vtt" in want:
        p = unique_output_path(outdir, stem, "vtt", overwrite)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("WEBVTT\n\n")
            for r in segs:
                fh.write(f"{hhmmss(r['start'], '.')} --> {hhmmss(r['end'], '.')}\n{r['text']}\n\n")
        written.append(p)

    return written


def collect_targets(raw: str) -> list[str]:
    p = win_to_wsl(raw)
    if os.path.isdir(p):
        files = sorted(
            os.path.join(p, f) for f in os.listdir(p)
            if os.path.splitext(f)[1].lower() in MEDIA_EXT
        )
        if not files:
            log(f"No se encontraron audios ni videos dentro de la carpeta: {os.path.basename(p)}", KAOMOJI_SHRUG, C_YELLOW)
        else:
            log(f"Carpeta detectada -> {len(files)} archivo(s) listos para transcribir", KAOMOJI_LOAD, C_CYAN)
        return files
    return [raw]


def process_one(src_raw: str, args, key: str | None, idx: int, total: int) -> tuple[int, str]:
    src = win_to_wsl(src_raw)
    if not os.path.isfile(src):
        log(f"No se encontro el archivo: {src}", KAOMOJI_ERR, C_RED)
        return 2, DEFAULT_OUTDIR
    if os.path.getsize(src) == 0:
        log(f"El archivo esta vacio (0 bytes): {src}", KAOMOJI_ERR, C_RED)
        return 2, DEFAULT_OUTDIR

    rem = total - idx
    queue_tag = f"[{idx}/{total} | faltan {rem}]" if total > 1 else ""
    if total > 1:
        log(f"Transcribiendo archivo {idx} de {total} (quedan {rem} mas)", KAOMOJI_WORK[0], C_YELLOW)

    stem = os.path.splitext(os.path.basename(src))[0]
    outdir = win_to_wsl(args.out_dir) if args.out_dir else DEFAULT_OUTDIR
    os.makedirs(outdir, exist_ok=True)
    if not os.access(outdir, os.W_OK):
        outdir = DEFAULT_OUTDIR

    backend = "local" if args.backend == "auto" else args.backend
    log(f"Archivo : {os.path.basename(src)}", "", C_BOLD)

    workdir = tempfile.mkdtemp(prefix="transcriptor_")
    _ACTIVE_TEMP_DIRS.add(workdir)
    log_path = os.path.join(workdir, "segments.jsonl")
    t0 = time.time()
    try:
        if backend == "local":
            wav = to_media_wav(src, workdir)
            try:
                segs, meta = transcribe_local(wav, args, log_path, queue_tag)
            except Exception as e:
                if args.backend == "auto" and key:
                    log(f"Usando respaldo en la nube (Deepgram)...", KAOMOJI_SHRUG, C_YELLOW)
                    segs, meta = transcribe_deepgram(src, args, key, log_path)
                else:
                    raise
        else:
            if not key:
                log("No hay clave configurada para Deepgram.", KAOMOJI_ERR, C_RED)
                return 3, outdir
            segs, meta = transcribe_deepgram(src, args, key, log_path)
    finally:
        if not args.keep_wav:
            shutil.rmtree(workdir, ignore_errors=True)
            _ACTIVE_TEMP_DIRS.discard(workdir)

    if not segs:
        log("No se detecto voz humana en este archivo.", KAOMOJI_SHRUG, C_YELLOW)
        return 4, outdir

    files = write_outputs(segs, meta, src, outdir, stem, args.format, args.overwrite)
    dur = segs[-1]["end"]
    elapsed = time.time() - t0
    speed = (dur / elapsed) if elapsed > 0 else 0
    log(f"¡Terminado en {elapsed:.1f}s! (Audio de {dur/60:.1f} min procesado a {speed:.1f}x de velocidad)",
        KAOMOJI_SAVE, C_GREEN)
    for f in files:
        log(f"  Guardado en -> {f}", "", C_CYAN)
    return 0, outdir


def main() -> int:
    setup_env.enable_windows_ansi()
    cfg = setup_env.load_config()

    ap = argparse.ArgumentParser(description="TRANSCRIPTOR SUITE (Automatico con o sin GPU)")
    ap.add_argument("--src", default="", help="ruta del video/audio o carpeta")
    ap.add_argument("--auto-run", action="store_true",
                    help="Modo 100% automatico para usuario final: busca en audio/ o abre ventana para elegir archivo")
    ap.add_argument("--setup", action="store_true", help="evalua hardware, instala dependencias y elige modelo IA")
    ap.add_argument("--prefs", action="store_true", help="abre ajustes simples")
    ap.add_argument("--doctor", action="store_true", help="verifica y repara el entorno automaticamente")
    ap.add_argument("--repair", action="store_true", help="reinstala el entorno virtual")
    ap.add_argument("--backend", default=os.environ.get("TRANSCRIPTOR_BACKEND", "auto"),
                    choices=["auto", "local", "deepgram"])
    ap.add_argument("--preset", default=cfg.get("default_preset", "fast"),
                    choices=["fast", "balanced", "quality"])
    ap.add_argument("--format", default=cfg.get("default_format", "txt"),
                    choices=["txt", "md", "json", "jsonl", "srt", "vtt", "all"])
    ap.add_argument("--device", default="auto", choices=["auto", "cuda", "igpu", "cpu"])
    ap.add_argument("--compute_type", default="",
                    choices=["", "int8", "int8_float16", "int8_float32", "float16", "float32", "default"])
    ap.add_argument("--lang", default=cfg.get("default_lang", "es"))
    ap.add_argument("--detect-language", action="store_true", default=bool(cfg.get("detect_language", False)))
    ap.add_argument("--overwrite", action="store_true", default=bool(cfg.get("overwrite_outputs", False)))
    ap.add_argument("--no-open", action="store_true", help="no abrir carpeta salidas al finalizar")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--batch-size", type=int, default=0)
    ap.add_argument("--beam-size", type=int, default=0)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--igpu-bin", default="")
    ap.add_argument("--igpu-model", default="")
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--queue-idx", type=int, default=0)
    ap.add_argument("--queue-total", type=int, default=0)
    ap.add_argument("--diarize", action="store_true")
    ap.add_argument("--dg-model", default="nova-3")
    ap.add_argument("--keep-wav", action="store_true")
    args = ap.parse_args()

    if args.doctor or args.repair:
        rc = setup_env.run_doctor(repair=args.repair)
        if not args.src and not args.auto_run:
            return rc

    if args.prefs:
        setup_env.configure_preferences()
        if not args.src and not args.auto_run:
            return 0

    if args.setup:
        setup_env.run_setup(auto_accept=False, force_select=True)
        if not args.src and not args.auto_run:
            return 0

    # Asegurar que el entorno y el modelo estan listos (reutilizando si ya existen)
    if not setup_env.is_environment_ready() and (args.backend in ("auto", "local")):
        setup_env.run_setup(auto_accept=False, force_select=False)

    # Si el Python actual NO tiene faster-whisper pero existe el venv creado por setup_env, relanzar con el Python listo
    hw = setup_env.inspect_hardware()
    ready_py = setup_env.find_ready_python(hw)
    if ready_py and os.path.abspath(ready_py) != os.path.abspath(sys.executable):
        cmd = [ready_py, os.path.abspath(__file__), *sys.argv[1:]]
        return subprocess.call(cmd)

    targets: list[str] = []
    if args.src:
        targets = collect_targets(args.src)
    elif args.auto_run:
        audio_files = sorted(
            os.path.join(setup_env.AUDIO_DIR, f)
            for f in os.listdir(setup_env.AUDIO_DIR)
            if os.path.splitext(f)[1].lower() in MEDIA_EXT
        ) if os.path.isdir(setup_env.AUDIO_DIR) else []

        if audio_files:
            log(f"Se encontraron {len(audio_files)} archivo(s) en la carpeta 'audio/'. Procesando automaticamente...",
                KAOMOJI_LOAD, C_GREEN)
            targets = audio_files
        else:
            log("Abriendo ventana para que elijas tu archivo de audio o video...", KAOMOJI_LOAD, C_CYAN)
            picked = setup_env.open_Native_file_dialog()
            if picked:
                targets = picked
            elif sys.stdin.isatty():
                raw_in = input("Arrastra aqui tu archivo de audio/video y presiona ENTER: ").strip()
                if raw_in:
                    targets = collect_targets(raw_in)

    if not targets:
        log("No se selecciono ningun archivo.", KAOMOJI_SHRUG, C_YELLOW)
        return 2

    key = find_deepgram_key()
    rc = 0
    last_outdir = DEFAULT_OUTDIR
    if args.queue_total > 1 and len(targets) == 1:
        rc, last_outdir = process_one(targets[0], args, key, args.queue_idx or 1, args.queue_total)
    else:
        total = len(targets)
        for idx, t in enumerate(targets, 1):
            r_one, last_outdir = process_one(t, args, key, idx, total)
            if r_one != 0:
                rc = r_one

    if rc == 0 and cfg.get("auto_open_outputs", True) and not args.no_open and args.queue_idx in (0, args.queue_total):
        open_folder_for_user(last_outdir)

    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{C_YELLOW}{KAOMOJI_SHRUG} Cancelado por el usuario.{C_RESET}")
        sys.exit(130)
    except Exception as exc:
        log(f"Ocurrio un problema: {exc}", KAOMOJI_ERR, C_RED)
        log("Intentando verificar el programa automaticamente...", "", C_YELLOW)
        try:
            setup_env.run_doctor(repair=False)
        except Exception:
            pass
        sys.exit(1)
