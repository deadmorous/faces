# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the application

The package is **not installed** — run it directly from the repo root:

```bash
python -m faces [OPTIONS] COMMAND [ARGS]
```

Common invocations:
```bash
python -m faces scan ~/Photos
python -m faces scan --debug-crops /tmp/dbg ~/Photos
python view_crops.py ~/Photos/IMG_9579.JPG /tmp/dbg
```

## Dependencies

Key runtime dependencies are **not listed in `pyproject.toml`** (only `click` and `pyyaml` are). The ML stack must be present in the active Python environment:

- `torch`, `torchvision` — PyTorch
- `facenet-pytorch` — provides `InceptionResnetV1` for 512-d face embeddings
- `retinaface-pytorch` — face detector (`resnet50_2020-07-20` weights, auto-downloaded on first run to `~/.cache/torch/hub/`)
- `Pillow`, `numpy` (<2.0), `matplotlib`

**numpy must stay below 2.0** — `retinaface-pytorch` pulls in numpy 2.x which breaks the torch↔numpy bridge. Pin with `pip install "numpy<2.0.0"` if it gets upgraded.

## Architecture

### Data flow for `scan`

```
JPEG files → detect_faces() → FaceDetection(bbox, score, embedding, image_size)
                                     ↓                    ↓
                              printed to stdout     written to JSON (--debug-crops)
```

### `faces/scanner.py` — the ML core

Central module. Contains:
- `FaceDetection` dataclass — the unit of work flowing between detection and future storage/clustering
- `detect_faces(path)` — opens image, runs RetinaFace detector, crops each face, runs InceptionResnetV1, returns `list[FaceDetection]`
- Module-level lazy singletons `_detector` / `_resnet` — models load once on first call, third-party `UserWarning`s suppressed during load

### Configuration (`faces/config.py`)

`Config` dataclass with fields: `database`, `photos_dir`, `cluster_threshold`. `load()` searches for config files in order: `~/.config/faces/config.yaml` → `~/.faces.yaml` → `./faces.yaml`. CLI options passed to the group always override config file values. The `Config` object is stored in Click's `ctx.obj` and passed to every subcommand via `@click.pass_obj`.

### Commands (`faces/commands/`)

Each command is a standalone module with a Click-decorated function. `clusterize`, `rename`, and `show` are stubs. `scan` is implemented: it globs for `*.jpg / *.jpeg / *.JPG / *.JPEG`, calls `scan_photo()` per file, and optionally writes per-photo JSON bbox files to `--debug-crops DIR`.

### `view_crops.py` — standalone visualisation utility

Not part of the `faces` package. Takes `PHOTO CROPS_DIR` on the command line, reads `CROPS_DIR/{photo_stem}.json`, and displays boxes with confidence scores via matplotlib.

## Debug crops JSON format

```json
{
  "photo": "/absolute/path/to/photo.jpg",
  "width": 5184,
  "height": 3456,
  "faces": [
    {"bbox": [x1, y1, x2, y2], "score": 0.99}
  ]
}
```

One file per photo, named `{stem}.json`. Coordinates are in original image pixels.
