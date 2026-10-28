# salvaramos-reels

Edición reproducible de reels para @salvaramos.cl. Cada reel nuevo sale con el estilo de la cuenta
cambiando solo su `config.yaml`.

## Setup

```bash
sudo apt install ffmpeg
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Un reel nuevo

1. Copia los videos a `projects/<slug>/raw/`.
2. Escribe `projects/<slug>/config.yaml` (ver `projects/jing-2026/config.yaml`):
   - `clips`: orden, `trim: [desde, hasta]` en segundos del raw, `broll: true` para planos sin voz.
   - `inserts`: `pip` o `fullscreen`, con `at` / `until` / `duration` y `text` para la promo.
   - `texts`: títulos (`style: title`) o promo (`style: promo`).
3. `.venv/bin/python src/render.py projects/<slug> --preview` y revisa `build/<slug>.preview.sheet.png`.
4. Corrige a mano `projects/<slug>/transcript.json` (Whisper se equivoca con nombres y chilenismos).
5. Render final sin `--preview`.
