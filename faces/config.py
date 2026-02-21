from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

DEFAULT_CONFIG_PATHS = [
    Path("~/.config/faces/config.yaml").expanduser(),
    Path("~/.faces.yaml").expanduser(),
    Path("faces.yaml"),
]


@dataclass
class Config:
    database: Path = Path("~/.local/share/faces/index.db")
    photos_dir: Optional[Path] = None
    cluster_threshold: float = 0.6

    def _resolve(self) -> "Config":
        self.database = Path(self.database).expanduser().resolve()
        if self.photos_dir is not None:
            self.photos_dir = Path(self.photos_dir).expanduser().resolve()
        return self


def load(config_file: Optional[str] = None) -> Config:
    """Return a Config populated from a YAML file and resolved to absolute paths.

    Searches DEFAULT_CONFIG_PATHS when *config_file* is not given.
    Missing config files are silently ignored (defaults are used instead),
    unless the caller explicitly named a file that does not exist.
    """
    cfg = Config()

    if config_file is not None:
        path = Path(config_file)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
        candidates = [path]
    else:
        candidates = DEFAULT_CONFIG_PATHS

    for path in candidates:
        if path.exists():
            with open(path) as fh:
                data = yaml.safe_load(fh) or {}
            if "database" in data:
                cfg.database = Path(data["database"])
            if "photos_dir" in data:
                cfg.photos_dir = Path(data["photos_dir"])
            if "cluster_threshold" in data:
                cfg.cluster_threshold = float(data["cluster_threshold"])
            break

    return cfg._resolve()
