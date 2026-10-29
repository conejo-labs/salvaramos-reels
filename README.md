# salvaramos-reels

Pipeline para editar los reels de [@salvaramos.cl](https://instagram.com/salvaramos.cl) siempre con el mismo estilo:
subtítulos palabra a palabra, presentaciones, preguntas sobre b-roll, memes y cortina final con el logo. Cada reel es
un archivo `config.yaml`; el estilo de la marca vive en `presets/style.yaml`.

Stack: Python + ffmpeg (libass) + faster-whisper. No hay editor gráfico: se edita el config y se renderiza.

## Qué va en el repo y qué va en Drive

| Qué | Dónde |
|---|---|
| Código, estilo, configs de cada reel, transcripciones, catálogo de memes, logos, fuentes, sonidos | Este repo |
| Videos crudos de cada evento y packs de memes y efectos | Unidad de Google Drive **SalvaRamos Reels** |
| Videos terminados | Drive, en `entregas/<evento>/` |

En Drive:

```
SalvaRamos Reels/
  eventos/<evento>/raw/   ← lo que se grabó, tal cual sale del celular; nunca se edita
  memes/pack/             ← los memes que describe assets/memes/catalog.yaml
  sfx/pack/               ← los efectos que describe assets/sfx/catalog.yaml
  entregas/<evento>/      ← versiones finales y para WhatsApp
```

En tu máquina eso se refleja en `media/` (fuera de git): `media/eventos/<evento>/raw/`, `media/memes/pack/`
y `media/sfx/pack/`.

## Instalación

Funciona en Linux, macOS y Windows con WSL2 (Ubuntu 24.04). En Windows, todo lo que sigue se corre dentro de WSL.

```bash
sudo apt install ffmpeg rclone python3-venv      # en macOS: brew install ffmpeg rclone
git clone git@github.com:conejo-labs/salvaramos-reels.git
cd salvaramos-reels
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

- ffmpeg tiene que ser 6 o más nuevo y traer `libass` y `zscale`; el de Ubuntu 24.04 sirve. `render.py` lo revisa al
  arrancar y avisa si falta algo.
- La primera transcripción descarga el modelo de Whisper (`large-v3-turbo`, ~1,6 GB).
- Sin GPU funciona igual, en CPU. Con una GPU NVIDIA y CUDA se usa sola.

## Conectar Google Drive (una vez por máquina)

```bash
rclone config create salvaramos drive scope=drive
```

Abre el navegador para autorizar la cuenta de Google que tiene acceso a la unidad **SalvaRamos Reels**. Si la unidad
es compartida (una «unidad compartida» de Workspace), corre `rclone config` y en el remoto `salvaramos` responde que
sí a «Configure this as a Shared Drive» y elige la unidad.

Si tu remoto o la carpeta se llaman distinto, indícalo con una variable de entorno:

```bash
export SALVARAMOS_DRIVE="otro-remoto:Carpeta"
```

## Material

```bash
.venv/bin/python src/material.py pull jing-2026            # baja los raws del evento y los packs
.venv/bin/python src/material.py upload jing-2026          # sube los raws que tengas en media/eventos/jing-2026/raw
.venv/bin/python src/material.py upload-memes              # sube media/memes/pack
.venv/bin/python src/material.py upload-sfx                # sube media/sfx/pack
.venv/bin/python src/material.py deliver projects/jing-2026-parte-1          # versión WhatsApp + sube a entregas/
.venv/bin/python src/material.py deliver projects/jing-2026-parte-1 --local  # solo la versión WhatsApp
.venv/bin/python src/material.py deliver projects/jing-2026-parte-1 --version sonido --local  # de otra versión
```

Todos usan `rclone copy`: suben o bajan lo que falta y **nunca borran** nada en Drive ni en tu máquina.

Para agregar un meme: déjalo en `media/memes/pack/`, súmalo a `assets/memes/catalog.yaml` (qué es, audio, para qué
sirve, `volumen_medio_db`) y corre `upload-memes`. Solo memes que se conozcan en Chile.

Para agregar un efecto: déjalo en `media/sfx/pack/` como `<id>.wav`, súmalo a `assets/sfx/catalog.yaml` con su
categoría, `recorte`, `pico`, `volumen_medio_db` y `volumen_pico_db`, y corre `upload-sfx`. Para escucharlos todos,
`.venv/bin/python src/sfx.py` genera `assets/sfx/catalogo.html`.

## Hacer un reel

1. **Grabar y subir.** El equipo sube los videos desde el celular a `eventos/<evento>/raw/` en Drive. Un evento puede
   dar varios reels (el JING dio dos partes).
2. **Bajar el material.** `material.py pull <evento>`.
3. **Escribir el config** en `projects/<reel>/config.yaml`. Lo más rápido es copiar uno del mismo estilo
   (`projects/jing-2026-parte-2/config.yaml`) y cambiar los tramos. Ver la referencia más abajo.
4. **Preview.** `.venv/bin/python src/render.py projects/<reel> --preview` renderiza los primeros 10 s en baja.
   Revisa `projects/<reel>/build/<reel>.preview.sheet.png`: un frame por segundo, con la zona donde va la interfaz de
   Instagram teñida de rojo.
5. **Corregir subtítulos.** Whisper se equivoca con nombres y chilenismos. No edites `transcript.json`: agrega reglas en
   `transcription.corrections` del config (ver abajo), que sobreviven a cualquier recorte.
6. **Render final.** `.venv/bin/python src/render.py projects/<reel>`. Deja en `build/` el video, su contact sheet,
   `subtitles.ass`, `timeline.json` y actualiza `projects/<reel>/minutaje.md`, que lista cada clip con su tramo del raw.
7. **Entregar.** `material.py deliver projects/<reel>`.

Cada etapa guarda su resultado en `build/` y se salta si nada cambió, así que el segundo render es mucho más rápido.
`--retranscribe` fuerza transcribir de nuevo.

Para elegir memes: `.venv/bin/python src/memes.py projects/<reel> --force` genera `assets/memes/catalogo.md` con cada
momento del reel donde cabe un meme y el catálogo con miniaturas.

## Referencia del config

```yaml
title: "JING 2026 · Parte 2 — ¿Ramos o final?"
event: jing-2026          # carpeta de Drive con los raws; src: raw/... se busca ahí
speed: 1.0                # acelera todo el reel sin cambiar el tono

transcription:
  vocabulary: [JING, la Cato, UdeC]               # palabras que Whisper debe conocer
  corrections:
    - {find: "Salva Ramos", replace: "SalvaRamos"}             # en todo el reel
    - {clip: tomas-calculo, find: "con buen", replace: "Como un buen"}   # solo en ese clip

clips:            # en orden; cada uno necesita un id único
  - id: hook
    src: raw/IMG_1699.MOV
    trim: [14.0, 23.8]              # segundos del raw
    remove: [[19.86, 20.38]]        # tramos a sacar (una muletilla)
  - id: ignacia-quien
    src: raw/IMG_1705.MOV
    trim: [[3.55, 4.25], [5.65, 6.45]]   # varios tramos: una frase armada con palabras exactas
    nametag: "Ignacia\nU. de los Andes · Just Dance"
  - id: pregunta-ramos
    src: raw/IMG_1705.MOV
    trim: [23.05, 26.2]
    title: "¿Pasar todos los ramos\no ganar la final?"
    cover:                          # tapa el clip con b-roll y deja la voz
      - {src: raw/IMG_1687.MOV, src_in: 3.0}
      - {src: raw/IMG_1756.MOV, src_in: 0.5}
  - id: meme-dificil
    meme: diablo-que-dificil        # pausa con el audio del meme
    trim: [0.5, 3.2]                # segundos dentro del meme
  - id: cierre
    card: cierre                    # cortina animada definida en style.yaml

inserts:          # cosas encima del video
  - type: pip
    meme: bateman-sonrisa
    position: arriba
    src_in: 0
    at: {word: aplicados, offset: -3.5}
    until: {clip: vicente-favorita}

texts:
  - style: headline
    text: "SalvaRamos\nen los JING"
    at: {clip: hook}
    until: {clip: hook-congelado}
    reveal: 3.8                     # aparece letra por letra en 3,8 s
```

**Tipos de clip** (según la clave que traen):

| Clave | Qué hace |
|---|---|
| (ninguna) | Voz: se cortan los silencios, se nivela el volumen y lleva subtítulos |
| `broll: true` | Toma de ambiente: sin cortes ni subtítulos, con el audio más bajo |
| `meme: <id>` | Pausa con el meme centrado sobre una copia desenfocada y con su audio |
| `freeze: <seg>` + `duration` | Congela ese frame; admite `look: bw` y `sfx: suspenso` |
| `card: <nombre>` | Cortina animada (`outro`, `cierre`) definida en `style.yaml` |

**Claves opcionales de un clip:** `nametag` (presentación: nombre y, en la segunda línea, universidad · deporte),
`title` (texto de pregunta), `cover` + `cover_from` (b-roll encima a partir de ese segundo), `silence_cut: false` (no
cortar silencios), `captions`, `gain_db`, `look`.

**Momentos** (`at`, `until`): un número de segundos del reel, `{clip: id, offset: s}` (inicio del clip; con
`edge: end`, su final) o `{word: palabra, occurrence: n, offset: s}`. Conviene anclar a clips o palabras: si cambia un
corte, el meme se mueve con la palabra.

**Inserts:** `type: pip` o `fullscreen`, `src` o `meme`, `src_in` (desde qué segundo del archivo), `position: arriba`
para los PiP, `text` para un texto promo encima de un fullscreen, `audio: true` para que suene el audio del insert
(los memes se nivelan como los de pausa; un PiP con su propio audio no lleva el efecto de `sfx.rules`).

**Estilos de texto:** `title`, `headline`, `nametag`, `promo` en `presets/style.yaml`.

**Efectos de sonido:** un bloque `sfx` en el config los activa. Con `auto: true`, cada evento del reel lleva el efecto
que dice `sfx.rules` en `presets/style.yaml` (whoosh en los cortes con flash, golpe en las preguntas y la promo, pop
en los nametags, boom en los PiP, riser antes de la cortina). `cues` suma efectos a mano:

```yaml
sfx:
  auto: true
  cues:
    - {sound: reloj, at: {clip: hook}, gain_db: -6}
```

Un cue acepta `gain_db`, `duration` (usa solo los primeros segundos del recorte) y `align: start` (arranca en `at`
en vez de hacer caer ahí el pico: para música o coros, cuyo pico llega tarde). Para una reacción inmediata, ancla
el cue a la última palabra del remate con un `offset` de unas décimas.

Cada efecto se ubica para que su pico caiga justo en el momento `at`, y su volumen pico se iguala con `sfx.levels`
según su categoría. Sin bloque `sfx`, el reel no lleva efectos.

**Otra versión sin pisar la actual:** `render.py projects/<reel> --version sonido` escribe
`build/<reel>.sonido.mp4` y deja intacto `build/<reel>.mp4`.

## Problemas comunes

- **Se perdió una palabra dicha muy bajo.** El corte de silencios la tomó como silencio: pon `silence_cut: false` en
  ese clip o empieza el `trim` un poco antes.
- **Un subtítulo dice algo mal.** Regla en `transcription.corrections`; el `find` tiene que coincidir con las palabras
  exactas que escribió Whisper (míralas en `transcript.json`).
- **Una palabra del subtítulo aparece en la persona equivocada.** No debería pasar: se transcribe clip por clip. Si
  pasa, `--retranscribe`.
- **«Al ffmpeg instalado le faltan filtros».** Usa el ffmpeg del sistema (`apt`/`brew`), no uno mínimo.
- **«No encuentro rclone».** Instálalo y conecta Drive (arriba).
