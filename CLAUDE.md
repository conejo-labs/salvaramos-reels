# salvaramos-reels

Pipeline reproducible para los reels de @salvaramos.cl: Python + ffmpeg (libass) + faster-whisper.
Un reel = un `projects/<slug>/config.yaml`; todo el estilo vive en `presets/style.yaml`.

## Correr

```bash
.venv/bin/python src/render.py projects/<slug> --preview   # primeros 10 s a 540x960
.venv/bin/python src/render.py projects/<slug>             # final 1080x1920
.venv/bin/python -m pytest -q tests
```

Salida en `projects/<slug>/build/`: `<slug>.mp4`, `<slug>.sheet.png` (contact sheet, 1 frame/s, con la
zona insegura de Reels teñida de rojo), `timeline.json` y `subtitles.ass`.

## Etapas

`normalize` → `cut` → `transcribe` → `compose` (timeline → ASS → ffmpeg) → `review`.
Cada etapa escribe en `build/` junto a un `.key` con el hash de sus inputs, su config y su propio código;
si el hash no cambió, se salta.

## Contratos que no se ven en el código

- **`build/timeline.json` es el contrato para migrar a Remotion**: tiempos ya resueltos, overlays con su
  rect en px, textos y páginas de subtítulos. Un backend nuevo lee eso más `style.yaml`; no relee el config.
- **`transcript.json` se transcribe clip por clip** y cada clip guarda la `key` de lo que usó del raw: si un
  clip cambia, solo ese se retranscribe y su versión anterior pasa a `previous`.
- **Las correcciones de subtítulos van en `transcription.corrections` del config**, no en `transcript.json`:
  `{find, replace}` sobre palabras exactas (con `clip` opcional) y se aplican después de cada transcripción,
  así sobreviven a cualquier recorte.
- El corte de silencios mide el volumen de cada clip cada 10 ms y conserva lo que supera su piso de ruido
  (percentil `cut.floor_percentile`) más `cut.above_floor_db`, acotado entre `min_db` y `max_db`. Si una palabra
  dicha muy bajo se pierde, el clip lleva `silence_cut: false` o un `trim` que empiece un poco antes.
- `speed` en el config acelera todo el reel al exportar (`setpts` + `atempo`, sin cambiar el tono). El timeline
  y el ASS van en tiempo sin acelerar; `timeline.json` trae `speed` para el backend que lo lea.
- Un texto con `reveal: <segundos>` aparece letra por letra en ese tiempo y queda completo hasta su `until`.
- **Los tiempos de `inserts` y `texts` son del timeline final**, y conviene anclarlos (`at: {clip: id}`,
  `at: {word: …}`) en vez de usar segundos: los cortes de silencio mueven todo lo que viene después.
- Tipos de clip, según la clave que traen:
  - por defecto, **voz**: se corta por silencio y lleva subtítulos;
  - `broll: true`: sin corte de silencio ni subtítulos, con el audio bajado (`audio.broll_gain_db`);
  - `meme: <id>`: pausa con el audio del meme, centrado sobre una copia desenfocada; `trim` es dentro del meme;
  - `freeze: <segundo>` + `duration`: congela ese frame, con `look` (p. ej. `bw`) y `sfx` de `assets/sfx/`.
- Un clip con `nametag` o `title` no lleva subtítulos (el texto los reemplaza). `cover` tapa el clip con b-roll
  repartido en partes iguales y deja su audio: así se presentan las preguntas con la voz del entrevistador.
- `trim` acepta varios rangos (`[[a, b], [c, d]]`) para armar una frase con palabras exactas del mismo raw.
- **El material binario vive en Google Drive y se refleja en `media/`** (fuera de git): `media/eventos/<evento>/raw/`
  y `media/memes/pack/`. `src/material.py` lo sincroniza con `rclone copy`, nunca con `sync`. Un config declara
  `event` y su `src: raw/...` se resuelve en `media/eventos/<event>/raw/`.
- `assets/memes/catalog.yaml` describe el pack (qué es, audio, encuadre, uso); `volumen_medio_db` fija la ganancia que
  iguala su volumen. Solo memes conocidos en Chile: los que no, se sacan del pack y del catálogo.
- `assets/sfx/suspenso.wav` es sintético (generado con ffmpeg): reemplázalo por uno real con el mismo nombre.

## Entorno (WSL)

- ffmpeg del sistema (Ubuntu 24.04, 6.1, con libass/zscale). `render.py` verifica los filtros al arrancar.
- CUDA no está disponible en esta máquina (NVML no inicializa): Whisper corre en CPU int8.
- PyAV 19 rompe `faster_whisper.decode_audio`; el audio se decodifica con ffmpeg a un array numpy.
- `media/` y todo `build/` están fuera de git. Los cambios llegan a `main` por PR.
