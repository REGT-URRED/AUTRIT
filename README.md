# Transcriptor Suite Local

Suite de transcripción automática de audio y video impulsada por IA local (`faster-whisper` / CTranslate2), diseñada para funcionar **sin conocimientos técnicos** tanto en equipos con tarjeta gráfica NVIDIA (GPU) como en computadoras sin GPU dedicada (CPU/RAM).

## Características principales

- **Cero configuración en equipos nuevos:** Al ejecutar `TRANSCRIBIR.bat` en una PC sin entorno previo, detecta si falta Python (ofreciendo instalación automática vía `winget`), crea un entorno virtual aislado, instala las dependencias necesarias (`faster-whisper`, `imageio-ffmpeg`, y librerías CUDA si hay GPU NVIDIA) y prepara todo automáticamente.
- **Reutilización inteligente de modelos:** Antes de descargar nada, escanea la carpeta local `modelos/`, `~/.hermes/models/` y la caché de HuggingFace (`~/.cache/huggingface/hub/`). Si ya tienes un modelo descargado, lo vincula automáticamente sin repetir descargas.
- **Selección adaptada al hardware:** Evalúa GPU (VRAM disponible), memoria RAM, hilos de CPU y espacio en disco para recomendar e instalar el modelo exacto (`tiny`, `base`, `small`, `medium`, `large-v3-turbo` o `large-v3`), bloqueando opciones que puedan congelar el equipo.
- **Recuperación automática ante errores:** Si ocurre falta de VRAM (OOM) en GPU, reduce progresivamente el `batch_size`, ajusta la precisión (`int8`) o continúa automáticamente en CPU sin perder la transcripción.
- **Múltiples formatos de salida:** Genera archivos `.txt`, `.md` (Markdown), `.srt`, `.vtt`, `.json` y `.jsonl`, protegiendo transcripciones anteriores mediante versionado automático (`archivo (1).txt`).
- **Compatible con Windows nativo y WSL (Ubuntu).**

---

## Uso rápido (sin conocimientos técnicos)

1. **Doble clic en `TRANSCRIBIR.bat`:**
   - Si no presionas nada en 4 segundos, inicia en modo automático.
   - Si hay archivos en la carpeta `audio/`, los procesa todos automáticamente; si está vacía, abre una ventana de Windows para elegir tu audio o video.
   - Al terminar, abre automáticamente la carpeta `salidas/` con el texto listo.
2. **Arrastrar y soltar:** Arrastra uno o varios archivos de audio/video (o una carpeta completa) directamente sobre `TRANSCRIBIR.bat`.
3. **Menú rápido (teclas `2`, `3`, `4` al iniciar):**
   - `[2]` Cambiar formato de salida, idioma o velocidad/calidad por defecto.
   - `[3]` Cambiar o descargar otro modelo de IA.
   - `[4]` Diagnóstico y reparación automática del entorno.

---

## Selección automática de modelos según hardware

| Modelo | Peso aprox. | Hardware recomendado |
| :--- | :---: | :--- |
| `tiny` | ~85 MB | Equipos muy limitados (< 2 GB RAM libre, solo CPU) |
| `base` | ~160 MB | PCs básicas sin GPU (2–3 GB RAM libre) |
| `small` | ~520 MB | Laptops/PCs estándar sin GPU (4+ GB RAM) o GPU de 2 GB |
| `medium` | ~1.6 GB | CPU potente (6+ hilos, 8+ GB RAM) o GPU de 3–4 GB VRAM |
| `large-v3-turbo` | ~1.7 GB | GPU NVIDIA con 4–6+ GB VRAM (mejor balance velocidad/calidad) |
| `large-v3` | ~3.2 GB | GPU NVIDIA de 6–8+ GB VRAM (máxima precisión) |

---

## Uso por línea de comandos (opcional)

```bash
# Modo automático (busca en audio/ o abre selector)
python3 transcribe_cli.py --auto-run

# Transcribir un archivo o carpeta específica
python3 transcribe_cli.py --src "ruta/al/video.mp4" --preset balanced --format md

# Verificar o reparar el entorno
python3 setup_env.py --doctor
python3 setup_env.py --repair
```

### Respaldo opcional en la nube (Deepgram)

Si deseas usar [Deepgram](https://deepgram.com/) como respaldo o motor principal:
1. Renombra `deepgram.key.example` a `deepgram.key`.
2. Pega tu API key dentro del archivo.

---

## Estructura del proyecto

```text
TRANSCRIPTOR/
├── TRANSCRIBIR.bat         # Lanzador principal para Windows / WSL
├── transcribe_cli.py       # Motor de transcripción y exportación
├── setup_env.py            # Auto-instalador, detector de hardware y gestor de modelos
├── requirements.txt        # Dependencias base
├── deepgram.key.example    # Plantilla opcional para API key de Deepgram
├── LEEME.txt               # Guía rápida para usuario final
├── audio/                  # Carpeta de entrada automática
├── modelos/                # Modelos locales descargados (ignorado en Git)
└── salidas/                # Transcripciones generadas (ignorado en Git)
```

## Subir a GitHub

```bash
git init
git add .
git commit -m "Initial commit: Transcriptor Suite"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
git push -u origin main
```

## Licencia

Distribuido bajo la licencia [MIT](LICENSE).
