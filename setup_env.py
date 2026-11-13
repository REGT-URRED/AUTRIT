#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TRANSCRIPTOR SUITE - Auto-instalacion 100% desatendida, deteccion de modelos
y paquetes ya existentes en la maquina (sin descargas ni instalaciones dobles),
y selector inteligente de modelo IA adaptado a los recursos reales del equipo.
"""
from __future__ import annotations

import argparse
import ctypes
import glob
import hashlib
import json
import os
import platform
import select
import shutil
import site
import subprocess
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(SCRIPT_DIR, "modelos")
AUDIO_DIR = os.path.join(SCRIPT_DIR, "audio")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "salidas")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "transcriptor_config.json")

IS_WINDOWS = os.name == "nt"
VENV_NAME = ".venv_win" if IS_WINDOWS else ".venv_wsl"
VENV_DIR = os.path.join(SCRIPT_DIR, VENV_NAME)

# Colores ANSI
C_RESET = "\033[0m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_MAGENTA = "\033[95m"
C_RED = "\033[91m"
C_DIM = "\033[90m"
C_BOLD = "\033[1m"

DEFAULT_PREFS = {
    "default_preset": "fast",
    "default_format": "txt",
    "default_lang": "es",
    "detect_language": False,
    "overwrite_outputs": False,
    "auto_open_outputs": True,
}

# Catalogo de modelos faster-whisper (CTranslate2) ordenados de menor a mayor
MODEL_CATALOG = [
    {
        "name": "tiny",
        "repo": "Systran/faster-whisper-tiny",
        "disk_mb": 85,
        "min_vram_mb": 600,
        "min_ram_mb": 1200,
        "speed_label": "Ultra rapido",
        "quality_label": "Basica (equipos muy limitados)",
    },
    {
        "name": "base",
        "repo": "Systran/faster-whisper-base",
        "disk_mb": 160,
        "min_vram_mb": 800,
        "min_ram_mb": 1800,
        "speed_label": "Muy rapido",
        "quality_label": "Ligera (PCs sencillas sin GPU)",
    },
    {
        "name": "small",
        "repo": "Systran/faster-whisper-small",
        "disk_mb": 520,
        "min_vram_mb": 1400,
        "min_ram_mb": 3200,
        "speed_label": "Rapido",
        "quality_label": "Buena (ideal para PC normal sin GPU)",
    },
    {
        "name": "medium",
        "repo": "Systran/faster-whisper-medium",
        "disk_mb": 1600,
        "min_vram_mb": 2600,
        "min_ram_mb": 6000,
        "speed_label": "Moderado",
        "quality_label": "Muy buena (alta precision en espanol)",
    },
    {
        "name": "large-v3-turbo",
        "repo": "Systran/faster-whisper-large-v3-turbo",
        "disk_mb": 1700,
        "min_vram_mb": 3400,
        "min_ram_mb": 7500,
        "speed_label": "Rapido en GPU",
        "quality_label": "Excelente (mejor balance calidad/velocidad)",
    },
    {
        "name": "large-v3",
        "repo": "Systran/faster-whisper-large-v3",
        "disk_mb": 3200,
        "min_vram_mb": 5200,
        "min_ram_mb": 11000,
        "speed_label": "Pesado",
        "quality_label": "Maxima precision (requiere tarjeta grafica potente)",
    },
]

# Orden de preferencia cuando ya hay modelos instalados en el equipo
MODEL_PRIORITY = ["large-v3-turbo", "large-v3", "medium", "small", "base", "tiny"]


def enable_windows_ansi() -> None:
    if not IS_WINDOWS:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def log(msg: str, color: str = "") -> None:
    ts = time.strftime("%H:%M:%S")
    body = f"{color}{msg}{C_RESET}" if color else msg
    print(f"{C_DIM}[{ts}]{C_RESET} {body}", flush=True)


def input_with_timeout(prompt: str, timeout_sec: int, default: str = "") -> str:
    """Pide un dato con cuenta regresiva; si el usuario no toca nada, usa el valor por defecto."""
    if not sys.stdin.isatty():
        return default
    if IS_WINDOWS:
        try:
            import msvcrt
            sys.stdout.write(f"{prompt} (auto en {timeout_sec}s): ")
            sys.stdout.flush()
            buf: list[str] = []
            t0 = time.time()
            while (time.time() - t0) < timeout_sec:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\r", "\n"):
                        print()
                        return "".join(buf).strip() or default
                    elif ch == "\x08":
                        if buf:
                            buf.pop()
                            sys.stdout.write("\b \b")
                            sys.stdout.flush()
                    else:
                        buf.append(ch)
                        sys.stdout.write(ch)
                        sys.stdout.flush()
                time.sleep(0.05)
            print()
            return "".join(buf).strip() or default
        except Exception:
            return default
    else:
        try:
            sys.stdout.write(f"{prompt} (auto en {timeout_sec}s): ")
            sys.stdout.flush()
            rlist, _, _ = select.select([sys.stdin], [], [], timeout_sec)
            if rlist:
                line = sys.stdin.readline().strip()
                return line or default
            print()
            return default
        except Exception:
            return default


def open_Native_file_dialog() -> list[str]:
    """Abre una ventana grafica nativa de Windows para elegir archivos si el usuario no sabe arrastrar."""
    ps_cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$f = New-Object System.Windows.Forms.OpenFileDialog; "
        "$f.Title = 'Selecciona el audio o video a transcribir'; "
        "$f.Filter = 'Archivos de Audio y Video|*.mp4;*.mkv;*.mov;*.avi;*.webm;*.flv;*.wmv;*.m4v;*.mp3;*.m4a;*.aac;*.wav;*.flac;*.ogg;*.opus;*.wma;*.amr|Todos los archivos (*.*)|*.*'; "
        "$f.Multiselect = $true; "
        "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { $f.FileNames -join '|' }"
    )
    if IS_WINDOWS:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=120,
            )
            out = r.stdout.strip()
            if out:
                return [p.strip() for p in out.split("|") if p.strip()]
        except Exception:
            pass
    elif shutil.which("powershell.exe"):
        try:
            r = subprocess.run(
                ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=120,
            )
            out = r.stdout.strip()
            if out:
                return [p.strip() for p in out.split("|") if p.strip()]
        except Exception:
            pass
    return []


def venv_python() -> str:
    if IS_WINDOWS:
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python3")


def active_python() -> str:
    """Devuelve el Python que tiene los paquetes listos (el actual del sistema/usuario o el del venv)."""
    vpy = venv_python()
    if os.path.isfile(vpy):
        return vpy
    return sys.executable


def is_in_venv() -> bool:
    return os.path.abspath(sys.prefix) == os.path.abspath(VENV_DIR)


def get_ram_info_mb() -> tuple[int, int]:
    if IS_WINDOWS:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys // (1024 * 1024)), int(stat.ullAvailPhys // (1024 * 1024))
        except Exception:
            return 8192, 4096
    else:
        total_mb, avail_mb = 8192, 4096
        try:
            with open("/proc/meminfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        total_mb = int(line.split()[1]) // 1024
                    elif line.startswith("MemAvailable:"):
                        avail_mb = int(line.split()[1]) // 1024
        except Exception:
            pass
        return total_mb, avail_mb


def get_nvidia_gpus() -> list[dict]:
    smi = shutil.which("nvidia-smi")
    if not smi and IS_WINDOWS:
        candidate = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
        if os.path.isfile(candidate):
            smi = candidate
    if not smi:
        return []
    try:
        r = subprocess.run(
            [smi, "--query-gpu=index,name,memory.free,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=6, check=True,
        )
        gpus = []
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                gpus.append({
                    "index": parts[0],
                    "name": parts[1],
                    "free_mb": int(float(parts[2])),
                    "total_mb": int(float(parts[3])),
                })
        return gpus
    except Exception:
        return []


def get_disk_free_mb(path: str) -> int:
    os.makedirs(path, exist_ok=True)
    usage = shutil.disk_usage(path)
    return int(usage.free // (1024 * 1024))


def compute_hw_fingerprint(hw: dict) -> str:
    gpu_name = hw["best_gpu"]["name"] if hw.get("best_gpu") else "none"
    gpu_vram = hw["best_gpu"]["total_mb"] if hw.get("best_gpu") else 0
    ram_gb = round(hw["ram_total_mb"] / 1024)
    raw = f"{hw['os']}|{hw['arch']}|{hw['cpu_threads']}|{ram_gb}|{gpu_name}|{gpu_vram}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def inspect_hardware() -> dict:
    total_ram, avail_ram = get_ram_info_mb()
    gpus = get_nvidia_gpus()
    best_gpu = max(gpus, key=lambda g: g["total_mb"]) if gpus else None
    disk_free = get_disk_free_mb(MODELS_DIR)
    cpu_threads = os.cpu_count() or 4
    hw = {
        "os": platform.system(),
        "arch": platform.machine(),
        "cpu_threads": cpu_threads,
        "ram_total_mb": total_ram,
        "ram_avail_mb": avail_ram,
        "gpus": gpus,
        "best_gpu": best_gpu,
        "disk_free_mb": disk_free,
    }
    hw["fingerprint"] = compute_hw_fingerprint(hw)
    return hw


def check_internet(timeout: float = 4.0) -> bool:
    for url in ("https://pypi.org", "https://huggingface.co"):
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=timeout):
                return True
        except Exception:
            continue
    return False


def has_ffmpeg(py_exe: str | None = None) -> bool:
    if shutil.which("ffmpeg"):
        return True
    if py_exe and os.path.isfile(py_exe):
        r = subprocess.run(
            [py_exe, "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip() and os.path.isfile(r.stdout.strip()):
            return True
    return False


def python_packages_ready(py_exe: str, need_cuda: bool) -> tuple[bool, list[str]]:
    if not py_exe or not os.path.isfile(py_exe):
        return False, ["python"]
    missing = []
    check_code = (
        "import importlib.util; "
        "mods=['faster_whisper','ctranslate2']; "
        "print(','.join(m for m in mods if importlib.util.find_spec(m) is None))"
    )
    r = subprocess.run([py_exe, "-c", check_code], capture_output=True, text=True)
    if r.returncode != 0:
        return False, ["faster-whisper", "ctranslate2"]
    out = r.stdout.strip()
    if out:
        missing.extend(out.split(","))

    if need_cuda:
        cuda_check = (
            "import site, os, glob; "
            "roots = []; "
            "try:\n roots.extend(site.getsitepackages())\nexcept Exception:\n pass\n"
            "try:\n roots.append(site.getusersitepackages())\nexcept Exception:\n pass\n"
            "roots.extend(glob.glob(os.path.expanduser('~/.local/lib/python*/site-packages'))); "
            "has_cublas = any(os.path.isdir(os.path.join(rt, 'nvidia', 'cublas')) for rt in roots if rt) "
            "or any(os.path.isfile(p) for p in ('/usr/lib/x86_64-linux-gnu/libcublas.so', '/usr/local/cuda/lib64/libcublas.so')); "
            "has_cudnn = any(os.path.isdir(os.path.join(rt, 'nvidia', 'cudnn')) for rt in roots if rt) "
            "or any(os.path.isfile(p) for p in ('/usr/lib/x86_64-linux-gnu/libcudnn.so', '/usr/local/cuda/lib64/libcudnn.so')); "
            "print(('1' if has_cublas else '0') + ('1' if has_cudnn else '0'))"
        )
        rc = subprocess.run([py_exe, "-c", cuda_check], capture_output=True, text=True)
        flags = rc.stdout.strip() if rc.returncode == 0 else "00"
        if len(flags) == 2:
            if flags[0] == "0":
                missing.append("nvidia-cublas-cu12")
            if flags[1] == "0":
                missing.append("nvidia-cudnn-cu12")
    return len(missing) == 0, missing


def load_config() -> dict:
    cfg = dict(DEFAULT_PREFS)
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict) -> None:
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


def _normalize_model_name(folder_or_path: str) -> str:
    """Extrae el nombre canonico del modelo a partir de rutas de cache, .hermes o carpetas locales."""
    low = folder_or_path.lower().replace("\\", "/")
    # Ordenar por longitud descendente para que 'large-v3-turbo' coincida antes que 'large-v3'
    for m in sorted(MODEL_CATALOG, key=lambda x: len(x["name"]), reverse=True):
        name = m["name"]
        if (
            low.endswith(f"/{name}")
            or f"faster-whisper-{name}" in low
            or f"whisper-{name}" in low
            or os.path.basename(low) == name
        ):
            return name
    base = os.path.basename(folder_or_path.rstrip("/\\"))
    if base.startswith("faster-whisper-"):
        return base[len("faster-whisper-"):]
    return base


def _is_valid_ct2_model_dir(path: str) -> bool:
    """Verifica si una carpeta contiene un modelo CTranslate2 / faster-whisper valido."""
    if not path or not os.path.isdir(path):
        return False
    return os.path.isfile(os.path.join(path, "model.bin"))


def get_installed_models() -> dict[str, str]:
    """
    Escanea TODOS los lugares donde el usuario ya pueda tener un modelo instalado
    para no volver a descargarlo nunca si ya existe en la maquina:
      1. Ruta personalizada en variable de entorno TRANSCRIPTOR_MODEL
      2. Ruta ya guardada en transcriptor_config.json
      3. Carpeta local ./modelos/ del proyecto
      4. Rutas previas en ~/.hermes/models/ y /home/*/.hermes/models/
      5. Cache oficial de HuggingFace (~/.cache/huggingface/hub/models--*faster-whisper-*)
      6. Cache en Windows (%USERPROFILE%/.cache/huggingface/hub/ desde WSL o Windows)
    Retorna {model_name: absolute_model_dir}.
    """
    found: dict[str, str] = {}

    def _register(candidate_dir: str, hint_name: str = "") -> None:
        if not _is_valid_ct2_model_dir(candidate_dir):
            return
        abs_dir = os.path.abspath(candidate_dir)
        mname = _normalize_model_name(hint_name or abs_dir)
        # Priorizar el primer hallazgo para ese nombre
        if mname not in found:
            found[mname] = abs_dir

    # 1) Variable de entorno
    env_m = os.environ.get("TRANSCRIPTOR_MODEL", "").strip()
    if env_m:
        _register(env_m)

    # 2) Configuracion guardada previamente
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                c = json.load(fh)
            cp = c.get("model_path", "")
            if cp:
                abs_cp = cp if os.path.isabs(cp) else os.path.join(SCRIPT_DIR, cp)
                _register(abs_cp, c.get("model_name", ""))
        except Exception:
            pass

    # 3) Carpeta ./modelos/ del proyecto (incluyendo subcarpetas directas o el propio directorio)
    if os.path.isdir(MODELS_DIR):
        _register(MODELS_DIR)
        for entry in sorted(os.listdir(MODELS_DIR)):
            full = os.path.join(MODELS_DIR, entry)
            _register(full, entry)
            # Revisar snapshots dentro de modelos/<entry>/snapshots/*
            snap_root = os.path.join(full, "snapshots")
            if os.path.isdir(snap_root):
                for sn in sorted(os.listdir(snap_root)):
                    _register(os.path.join(snap_root, sn), entry)

    # 4) Rutas clasicas del proyecto original (/home/toor/.hermes/models, ~/.hermes/models, etc.)
    hermes_roots = [
        "/home/toor/.hermes/models",
        os.path.expanduser("~/.hermes/models"),
    ]
    if not IS_WINDOWS:
        hermes_roots.extend(glob.glob("/home/*/.hermes/models"))
        hermes_roots.extend(glob.glob("/mnt/c/Users/*/.hermes/models"))
    else:
        hermes_roots.append(os.path.join(os.environ.get("USERPROFILE", ""), ".hermes", "models"))

    for hroot in dict.fromkeys(hermes_roots):
        if hroot and os.path.isdir(hroot):
            for entry in sorted(os.listdir(hroot)):
                full = os.path.join(hroot, entry)
                _register(full, entry)

    # 5) Cache estandar de HuggingFace Hub (Linux, WSL y Windows)
    hf_hub_dirs = [
        os.environ.get("HF_HUB_CACHE", ""),
        os.path.join(os.environ.get("HF_HOME", ""), "hub") if os.environ.get("HF_HOME") else "",
        os.path.expanduser("~/.cache/huggingface/hub"),
    ]
    if not IS_WINDOWS:
        hf_hub_dirs.extend(glob.glob("/home/*/.cache/huggingface/hub"))
        hf_hub_dirs.extend(glob.glob("/mnt/c/Users/*/.cache/huggingface/hub"))
    else:
        up = os.environ.get("USERPROFILE", "")
        if up:
            hf_hub_dirs.append(os.path.join(up, ".cache", "huggingface", "hub"))

    for hub in dict.fromkeys(hf_hub_dirs):
        if not hub or not os.path.isdir(hub):
            continue
        for entry in sorted(os.listdir(hub)):
            if "whisper" not in entry.lower():
                continue
            repo_dir = os.path.join(hub, entry)
            snap_root = os.path.join(repo_dir, "snapshots")
            if os.path.isdir(snap_root):
                for sn in sorted(os.listdir(snap_root), reverse=True):
                    _register(os.path.join(snap_root, sn), entry)

    return found


def pick_best_existing_model(installed: dict[str, str], hw: dict) -> tuple[str, str] | None:
    """
    Si el usuario ya tiene uno o varios modelos en su maquina, elige el mejor disponible
    que sea compatible con su equipo sin descargar nada nuevo.
    """
    if not installed:
        return None
    # Preferir el modelo que ya estaba configurado si sigue existiendo
    cfg = load_config()
    cfg_name = cfg.get("model_name", "")
    if cfg_name and cfg_name in installed:
        return cfg_name, installed[cfg_name]

    # Ordenar segun prioridad (large-v3-turbo -> large-v3 -> medium -> small -> base -> tiny)
    for pref in MODEL_PRIORITY:
        if pref in installed:
            return pref, installed[pref]

    # Cualquier otro modelo personalizado que tenga el usuario (ej. distil-whisper o carpeta propia)
    first_k = next(iter(installed))
    return first_k, installed[first_k]


def find_ready_python(hw: dict) -> str | None:
    """
    Revisa si el Python actual del sistema/usuario o el Python del venv ya tiene
    faster-whisper, ctranslate2 y ffmpeg listos para no reinstalar paquetes.
    """
    need_cuda = bool(hw["best_gpu"])
    for cand in (venv_python(), sys.executable):
        if not cand or not os.path.isfile(cand):
            continue
        ok_pkgs, _ = python_packages_ready(cand, need_cuda=need_cuda)
        if ok_pkgs and has_ffmpeg(cand):
            return cand
        # Si tiene los paquetes de faster-whisper aunque falte pip nvidia-* (porque usa CUDA del sistema), verificar ctranslate2
        ok_base, _ = python_packages_ready(cand, need_cuda=False)
        if ok_base and has_ffmpeg(cand):
            return cand
    return None


def is_environment_ready() -> bool:
    """
    Retorna True de inmediato si:
    1) Hay un Python (sistema o venv) con faster-whisper + ffmpeg listos, Y
    2) Ya existe al menos un modelo valido en la maquina (en modelos/, .hermes/, o cache HF).
    Si el modelo existe pero aun no estaba registrado en transcriptor_config.json, lo registra
    silenciosamente para no hacer doble trabajo ni mostrar menus innecesarios.
    """
    hw = inspect_hardware()
    py = find_ready_python(hw)
    if not py:
        return False

    installed = get_installed_models()
    if not installed:
        return False

    cfg = load_config()
    chosen = pick_best_existing_model(installed, hw)
    if not chosen:
        return False

    m_name, m_path = chosen
    # Si la config no apuntaba aun a este modelo existente, actualizarla silenciosamente
    if cfg.get("model_path") != m_path or not os.path.isfile(CONFIG_PATH):
        cfg.update({
            "model_name": m_name,
            "model_path": m_path,
            "python_exe": py,
            "detected_gpu": hw["best_gpu"]["name"] if hw["best_gpu"] else None,
            "detected_ram_mb": hw["ram_total_mb"],
            "hw_fingerprint": hw["fingerprint"],
            "configured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        save_config(cfg)
    return True


def create_venv_resilient() -> None:
    log("Preparando el motor interno del programa (solo la primera vez)...", C_CYAN)
    r = subprocess.run([sys.executable, "-m", "venv", VENV_DIR], capture_output=True, text=True)
    if r.returncode == 0 and os.path.isfile(venv_python()):
        return

    if os.path.isdir(VENV_DIR):
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    if not IS_WINDOWS:
        r2 = subprocess.run([sys.executable, "-m", "venv", "--without-pip", VENV_DIR], capture_output=True, text=True)
        if r2.returncode == 0 and os.path.isfile(venv_python()):
            try:
                get_pip = os.path.join(VENV_DIR, "get-pip.py")
                urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip)
                subprocess.run([venv_python(), get_pip], check=True)
                os.remove(get_pip)
                return
            except Exception:
                shutil.rmtree(VENV_DIR, ignore_errors=True)

        if shutil.which("apt-get"):
            py_ver = f"{sys.version_info.major}.{sys.version_info.minor}"
            subprocess.run(["sudo", "-n", "apt-get", "update", "-qq"], check=False)
            subprocess.run(["sudo", "-n", "apt-get", "install", "-y", f"python{py_ver}-venv"], check=False)
            r3 = subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=False)
            if r3.returncode == 0 and os.path.isfile(venv_python()):
                return

    raise RuntimeError("No se pudo crear el entorno interno de Python.")


def ensure_venv_and_deps(hw: dict, force_reinstall: bool = False) -> str:
    # Si no se pidio reinstalar a la fuerza y el sistema ya tiene todo listo, reutilizarlo sin instalar nada
    if not force_reinstall:
        existing_py = find_ready_python(hw)
        if existing_py:
            return existing_py

    py = venv_python()
    if force_reinstall and os.path.isdir(VENV_DIR):
        log("Reparando componentes internos...", C_YELLOW)
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    if not os.path.isfile(py):
        create_venv_resilient()

    need_cuda = bool(hw["best_gpu"])
    ok_pkgs, missing = python_packages_ready(py, need_cuda=need_cuda)
    need_ffmpeg_pkg = not has_ffmpeg(py)

    if ok_pkgs and not need_ffmpeg_pkg and not force_reinstall:
        return py

    if not check_internet():
        ok_cpu, _ = python_packages_ready(py, need_cuda=False)
        if ok_cpu and has_ffmpeg(py):
            log("Sin conexion a internet: se usaran los componentes ya instalados.", C_YELLOW)
            return py
        raise RuntimeError(
            "Se necesita conexion a internet solo la primera vez para descargar el motor de transcripcion."
        )

    subprocess.run([py, "-m", "pip", "install", "--upgrade", "pip", "-q"], check=False)

    pkgs_to_install = []
    if force_reinstall or not ok_pkgs:
        if force_reinstall or any(m in missing for m in ("faster_whisper", "faster-whisper", "ctranslate2", "python")):
            pkgs_to_install.append("faster-whisper>=1.0.0")
        if "nvidia-cublas-cu12" in missing or (force_reinstall and need_cuda):
            pkgs_to_install.append("nvidia-cublas-cu12")
        if "nvidia-cudnn-cu12" in missing or (force_reinstall and need_cuda):
            pkgs_to_install.append("nvidia-cudnn-cu12")

    if force_reinstall or need_ffmpeg_pkg:
        pkgs_to_install.append("imageio-ffmpeg")

    if pkgs_to_install:
        log("Instalando motor de Inteligencia Artificial y lector de audio/video...", C_CYAN)
        log("Por favor espera, esto se hace automaticamente una sola vez...", C_DIM)
        subprocess.run([py, "-m", "pip", "install", "--upgrade", *pkgs_to_install], check=True)
        log("Componentes instalados con exito.", C_GREEN)

    return py


def evaluate_models(hw: dict, installed: dict[str, str]) -> tuple[list[dict], str]:
    gpu = hw["best_gpu"]
    ram_total = hw["ram_total_mb"]
    ram_avail = hw["ram_avail_mb"]
    threads = hw["cpu_threads"]
    disk_free = hw["disk_free_mb"]

    eff_ram = max(ram_avail, int(ram_total * 0.70))

    evaluated = []
    best_auto = "tiny"

    for m in MODEL_CATALOG:
        already = m["name"] in installed
        disk_ok = already or (disk_free >= int(m["disk_mb"] * 1.25))
        if gpu:
            vram = gpu["total_mb"]
            vram_free = gpu["free_mb"]
            eff_vram = max(vram_free, int(vram * 0.80))
            if eff_vram >= m["min_vram_mb"] and disk_ok:
                status = "Ideal para tu GPU"
                fit = 3
            elif vram >= m["min_vram_mb"] * 0.85 and disk_ok:
                status = "Compatible (GPU)"
                fit = 2
            elif eff_ram >= m["min_ram_mb"] and disk_ok:
                status = "Usa CPU (mas lento)"
                fit = 1
            else:
                status = "No recomendado" if disk_ok else "Falta espacio disco"
                fit = 0
        else:
            if m["name"] in ("large-v3", "large-v3-turbo"):
                if eff_ram >= m["min_ram_mb"] and threads >= 8 and disk_ok:
                    status = "Lento sin GPU"
                    fit = 1
                else:
                    status = "Pesado p/ esta PC" if disk_ok else "Falta espacio disco"
                    fit = 0
            elif m["name"] == "medium":
                if eff_ram >= m["min_ram_mb"] and threads >= 6 and disk_ok:
                    status = "Ideal (PC potente)"
                    fit = 3
                elif eff_ram >= m["min_ram_mb"] * 0.85 and disk_ok:
                    status = "Compatible (lento)"
                    fit = 2
                else:
                    status = "Poca memoria RAM" if disk_ok else "Falta espacio disco"
                    fit = 0
            else:
                if eff_ram >= m["min_ram_mb"] and disk_ok:
                    status = "Ideal para tu PC"
                    fit = 3
                elif eff_ram >= m["min_ram_mb"] * 0.75 and disk_ok:
                    status = "Compatible"
                    fit = 2
                else:
                    status = "Poca memoria RAM" if disk_ok else "Falta espacio disco"
                    fit = 0

        item = dict(m)
        item["fit"] = fit
        item["status"] = status
        item["installed"] = already
        item["installed_path"] = installed.get(m["name"], "")
        evaluated.append(item)

    if gpu:
        candidates = [x for x in evaluated if x["fit"] >= 3]
        if candidates:
            names = [c["name"] for c in candidates]
            if "large-v3-turbo" in names and gpu["total_mb"] < 7000:
                best_auto = "large-v3-turbo"
            else:
                best_auto = candidates[-1]["name"]
        else:
            justos = [x for x in evaluated if x["fit"] >= 2]
            best_auto = justos[-1]["name"] if justos else "tiny"
    else:
        candidates = [x for x in evaluated if x["fit"] >= 3]
        if candidates:
            best_auto = candidates[-1]["name"]
        else:
            justos = [x for x in evaluated if x["fit"] >= 2]
            best_auto = justos[-1]["name"] if justos else "tiny"

    return evaluated, best_auto


def recommend_default_preset(hw: dict) -> str:
    if hw["best_gpu"] and hw["best_gpu"]["total_mb"] >= 4000:
        return "balanced"
    return "fast"


def print_hardware_and_models(hw: dict, evaluated: list[dict], recommended: str, installed: dict[str, str]) -> None:
    print()
    print(f"{C_CYAN}===================================================================={C_RESET}")
    print(f"{C_BOLD}  ANALISIS AUTOMATICO DE TU COMPUTADORA{C_RESET}")
    print(f"{C_CYAN}===================================================================={C_RESET}")
    print(f"  Procesador : {hw['cpu_threads']} hilos disponibles")
    print(f"  Memoria RAM: {hw['ram_avail_mb'] // 1024} GB libres de {hw['ram_total_mb'] // 1024} GB totales")
    if hw["best_gpu"]:
        g = hw["best_gpu"]
        print(f"  Tarjeta Video (GPU): {C_GREEN}SI - {g['name']} ({g['total_mb'] // 1024} GB VRAM){C_RESET}")
    else:
        print(f"  Tarjeta Video (GPU): {C_YELLOW}No tiene GPU dedicada (Funcionara en Modo Procesador/CPU){C_RESET}")
    if installed:
        print(f"  Modelos ya en tu PC: {C_GREEN}{', '.join(installed.keys())}{C_RESET}")
    print(f"{C_CYAN}--------------------------------------------------------------------{C_RESET}")
    print(f"  {'#':<2} {'Modelo IA':<16} {'Peso':<8} {'Compatibilidad':<20} {'Estado'}")
    print(f"  {'-'*2} {'-'*16} {'-'*8} {'-'*20} {'-'*26}")

    for idx, m in enumerate(evaluated, 1):
        is_rec = m["name"] == recommended
        tag_inst = " [YA INSTALADO]" if m["installed"] else ""
        tag_rec = " <-- RECOMENDADO" if is_rec else ""
        color = C_GREEN if (is_rec or m["installed"]) else (C_CYAN if m["fit"] >= 2 else C_DIM)
        size_str = f"{m['disk_mb']} MB" if m["disk_mb"] < 1000 else f"{m['disk_mb']/1000:.1f} GB"
        print(
            f"  {color}{idx:<2} {m['name']:<16} {size_str:<8} {m['status']:<20} "
            f"{m['speed_label']}{tag_inst}{tag_rec}{C_RESET}"
        )
    print(f"{C_CYAN}===================================================================={C_RESET}")
    print()


def download_model_in_venv(py_exe: str, model_info: dict, installed: dict[str, str]) -> str:
    # Si ya esta instalado en cualquier ruta detectada (.hermes, cache HF, o modelos/), devolver esa ruta sin descargar nada
    mname = model_info["name"]
    if mname in installed and _is_valid_ct2_model_dir(installed[mname]):
        log(f"Reutilizando el modelo '{mname}' que ya tienes en: {installed[mname]}", C_GREEN)
        return installed[mname]

    target_dir = os.path.join(MODELS_DIR, mname)
    if _is_valid_ct2_model_dir(target_dir):
        log(f"El modelo '{mname}' ya esta listo en tu computadora.", C_GREEN)
        return target_dir

    if not check_internet():
        if installed:
            fallback_name = next(iter(installed))
            log(f"Sin internet: usando el modelo '{fallback_name}' que ya tienes instalado.", C_YELLOW)
            return installed[fallback_name]
        raise RuntimeError(
            f"No hay conexion a internet para descargar el modelo '{mname}'."
        )

    os.makedirs(target_dir, exist_ok=True)
    log(
        f"Descargando el modelo '{mname}' ({model_info['disk_mb']} MB) por primera vez...",
        C_CYAN,
    )
    log("No cierres esta ventana...", C_DIM)

    dl_script = (
        "from huggingface_hub import snapshot_download; "
        f"snapshot_download(repo_id={model_info['repo']!r}, local_dir={target_dir!r})"
    )
    subprocess.run([py_exe, "-c", dl_script], check=True)
    if not _is_valid_ct2_model_dir(target_dir):
        raise RuntimeError("La descarga se interrumpio. Vuelve a intentarlo.")
    log(f"Modelo '{mname}' descargado y configurado.", C_GREEN)
    return target_dir


def run_setup(auto_accept: bool = False, force_select: bool = False) -> dict:
    enable_windows_ansi()
    os.makedirs(AUDIO_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(MODELS_DIR, exist_ok=True)

    hw = inspect_hardware()
    py_exe = ensure_venv_and_deps(hw)
    installed = get_installed_models()
    evaluated, recommended = evaluate_models(hw, installed)
    cfg = load_config()

    # REGLA CLAVE: Si la maquina YA tiene al menos un modelo instalado (en modelos/, .hermes/ o cache HF)
    # y el usuario NO pidio cambiar de modelo manualmente (--force), reutilizar el modelo existente de inmediato
    # sin descargar nada nuevo ni hacer doble trabajo.
    if not force_select and installed:
        existing = pick_best_existing_model(installed, hw)
        if existing:
            m_name, m_path = existing
            log(f"Modelo existente detectado automaticamente: '{m_name}' ({m_path})", C_GREEN)
            if "configured_at" not in cfg:
                cfg["default_preset"] = recommend_default_preset(hw)
                cfg["default_format"] = "txt"
                cfg["default_lang"] = "es"
                cfg["auto_open_outputs"] = True
            cfg.update({
                "model_name": m_name,
                "model_path": m_path,
                "python_exe": py_exe,
                "detected_gpu": hw["best_gpu"]["name"] if hw["best_gpu"] else None,
                "detected_ram_mb": hw["ram_total_mb"],
                "hw_fingerprint": hw["fingerprint"],
                "configured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            save_config(cfg)
            return cfg

    # Solo llegamos aqui si la maquina NO tiene ningun modelo en absoluto, o el usuario eligio "Cambiar modelo IA"
    print_hardware_and_models(hw, evaluated, recommended, installed)

    rec_idx = next(i for i, m in enumerate(evaluated, 1) if m["name"] == recommended)
    chosen_model = evaluated[rec_idx - 1]

    if force_select and sys.stdin.isatty() and not auto_accept:
        raw = input(
            f"Presiona ENTER para usar [{recommended}] o escribe el numero [1-{len(evaluated)}]: "
        ).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(evaluated):
            chosen_model = evaluated[int(raw) - 1]
    elif not auto_accept and sys.stdin.isatty():
        print(f"{C_GREEN}No se detectaron modelos previos. Se instalara el ideal para tu PC: {C_BOLD}{recommended}{C_RESET}")
        raw = input_with_timeout(
            f"Presiona ENTER para continuar (o escribe otro numero 1-{len(evaluated)})",
            timeout_sec=8,
            default=str(rec_idx),
        )
        if raw.isdigit() and 1 <= int(raw) <= len(evaluated):
            cand = evaluated[int(raw) - 1]
            if cand["fit"] == 0:
                log(
                    f"El modelo '{cand['name']}' es demasiado pesado para esta PC. "
                    f"Usando '{recommended}' para evitar que el equipo se congele.",
                    C_YELLOW,
                )
                chosen_model = evaluated[rec_idx - 1]
            else:
                chosen_model = cand
    else:
        log(f"Instalando automaticamente el modelo ideal para tu PC: '{recommended}'", C_GREEN)

    model_dir = download_model_in_venv(py_exe, chosen_model, installed)
    # Si el modelo esta dentro de SCRIPT_DIR guardamos ruta relativa portable; si esta en .hermes o cache HF, ruta absoluta
    try:
        rel_cand = os.path.relpath(model_dir, SCRIPT_DIR)
        stored_path = model_dir if rel_cand.startswith("..") else rel_cand
    except ValueError:
        stored_path = model_dir

    if "configured_at" not in cfg:
        cfg["default_preset"] = recommend_default_preset(hw)
        cfg["default_format"] = "txt"
        cfg["default_lang"] = "es"
        cfg["auto_open_outputs"] = True

    cfg.update({
        "model_name": chosen_model["name"],
        "model_path": stored_path,
        "python_exe": py_exe,
        "repo": chosen_model["repo"],
        "detected_gpu": hw["best_gpu"]["name"] if hw["best_gpu"] else None,
        "detected_ram_mb": hw["ram_total_mb"],
        "hw_fingerprint": hw["fingerprint"],
        "configured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_config(cfg)
    return cfg


def configure_preferences() -> None:
    enable_windows_ansi()
    cfg = load_config()
    print()
    print(f"{C_CYAN}===================================================================={C_RESET}")
    print(f"{C_BOLD}  AJUSTES POR DEFECTO{C_RESET}")
    print(f"{C_CYAN}===================================================================={C_RESET}")
    print(f"  1) Velocidad/Calidad : {C_GREEN}{cfg.get('default_preset', 'fast')}{C_RESET}")
    print(f"  2) Formato de salida : {C_GREEN}{cfg.get('default_format', 'txt')}{C_RESET}")
    print(f"  3) Idioma del audio  : {C_GREEN}{'Auto-detectar' if cfg.get('detect_language') else cfg.get('default_lang', 'es')}{C_RESET}")
    print(f"  4) Abrir carpeta al terminar: {C_GREEN}{'Si' if cfg.get('auto_open_outputs', True) else 'No'}{C_RESET}")
    print(f"{C_CYAN}--------------------------------------------------------------------{C_RESET}")

    print("\nVelocidad/Calidad: [1] Rapido (recomendado) | [2] Equilibrado | [3] Maxima calidad")
    m_in = input("Elegir [Enter = dejar como esta]: ").strip()
    if m_in == "1":
        cfg["default_preset"] = "fast"
    elif m_in == "2":
        cfg["default_preset"] = "balanced"
    elif m_in == "3":
        cfg["default_preset"] = "quality"

    print("\nFormato de archivo: [1] Texto (TXT) | [2] Word/Notas (MD) | [3] Subtitulos (SRT) | [4] Todos juntos")
    f_in = input("Elegir [Enter = dejar como esta]: ").strip()
    fmt_map = {"1": "txt", "2": "md", "3": "srt", "4": "all"}
    if f_in in fmt_map:
        cfg["default_format"] = fmt_map[f_in]

    print("\nIdioma del audio: [1] Espanol | [2] Ingles | [3] Detectar idioma automaticamente")
    l_in = input("Elegir [Enter = dejar como esta]: ").strip()
    if l_in == "1":
        cfg["default_lang"] = "es"
        cfg["detect_language"] = False
    elif l_in == "2":
        cfg["default_lang"] = "en"
        cfg["detect_language"] = False
    elif l_in == "3":
        cfg["detect_language"] = True

    save_config(cfg)
    log("Ajustes guardados correctamente.", C_GREEN)


def run_doctor(repair: bool = False) -> int:
    enable_windows_ansi()
    hw = inspect_hardware()

    print()
    print(f"{C_CYAN}===================================================================={C_RESET}")
    print(f"{C_BOLD}  ESTADO Y REPARACION AUTOMATICA DEL PROGRAMA{C_RESET}")
    print(f"{C_CYAN}===================================================================={C_RESET}")
    if hw["best_gpu"]:
        g = hw["best_gpu"]
        print(f"  Modo de aceleracion : {C_GREEN}GPU Dedicada ({g['name']} - {g['total_mb']//1024} GB){C_RESET}")
    else:
        print(f"  Modo de aceleracion : {C_YELLOW}Procesador / CPU ({hw['cpu_threads']} hilos, {hw['ram_total_mb']//1024} GB RAM){C_RESET}")

    if repair:
        ensure_venv_and_deps(hw, force_reinstall=True)

    py = find_ready_python(hw) or venv_python()
    ok_pkgs, _ = python_packages_ready(py, need_cuda=False)
    ff_ok = has_ffmpeg(py)
    installed = get_installed_models()

    if (not ok_pkgs or not ff_ok or not installed) and not repair:
        log("Detectamos elementos faltantes. Configurando automaticamente...", C_YELLOW)
        run_setup(auto_accept=True, force_select=False)
        py = find_ready_python(hw) or venv_python()
        ok_pkgs, _ = python_packages_ready(py, need_cuda=False)
        ff_ok = has_ffmpeg(py)
        installed = get_installed_models()

    cfg = load_config()
    print(f"  Motor interno       : {C_GREEN + 'LISTO' if ok_pkgs else C_RED + 'PENDIENTE'}{C_RESET} ({py})")
    print(f"  Lector Audio/Video  : {C_GREEN + 'LISTO' if ff_ok else C_RED + 'PENDIENTE'}{C_RESET}")
    print(f"  Modelo IA activo    : {C_GREEN}{cfg.get('model_name', 'Ninguno')}{C_RESET} -> {cfg.get('model_path', '')}")
    if installed:
        print(f"  Modelos detectados  : {', '.join(f'{k} ({v})' for k, v in installed.items())}")
    print(f"{C_CYAN}===================================================================={C_RESET}")
    return 0 if (ok_pkgs and ff_ok and bool(installed)) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Instalador y gestor automatico de TRANSCRIPTOR SUITE")
    ap.add_argument("--check", action="store_true", help="Verifica si ya existe modelo y entorno listos (exit 0/1)")
    ap.add_argument("--auto", action="store_true", help="Configura todo sin preguntar nada")
    ap.add_argument("--force", action="store_true", help="Muestra el selector de modelos IA para cambiar o descargar otro")
    ap.add_argument("--prefs", action="store_true", help="Abre ajustes simples")
    ap.add_argument("--doctor", action="store_true", help="Verifica y repara el programa automaticamente")
    ap.add_argument("--repair", action="store_true", help="Reinstala el entorno desde cero")
    ap.add_argument("--pick-file", action="store_true", help="Abre ventana grafica para elegir archivos")
    ap.add_argument("--print-python", action="store_true", help="Imprime el ejecutable Python listo para usar")
    args = ap.parse_args()

    if args.check:
        return 0 if is_environment_ready() else 1

    if args.print_python:
        hw = inspect_hardware()
        py = find_ready_python(hw) or venv_python()
        print(py if os.path.isfile(py) else sys.executable)
        return 0

    if args.pick_file:
        files = open_Native_file_dialog()
        for f in files:
            print(f)
        return 0 if files else 1

    if args.doctor or args.repair:
        return run_doctor(repair=args.repair)

    if args.prefs:
        configure_preferences()
        return 0

    run_setup(auto_accept=args.auto, force_select=args.force)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{C_YELLOW}Cancelado por el usuario.{C_RESET}")
        sys.exit(130)
    except Exception as exc:
        log(f"Aviso: {exc}", C_RED)
        sys.exit(1)
