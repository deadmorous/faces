"""Face detection and embedding extraction."""

from pathlib import Path
from typing import Optional

import torch
from facenet_pytorch import MTCNN, InceptionResnetV1
from PIL import Image

CONFIDENCE_THRESHOLD = 0.90

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Models are loaded once on first use.
_mtcnn: Optional[MTCNN] = None
_resnet: Optional[InceptionResnetV1] = None


def _models() -> tuple[MTCNN, InceptionResnetV1]:
    global _mtcnn, _resnet
    if _mtcnn is None:
        _mtcnn = MTCNN(image_size=160, margin=0, keep_all=True, device=device)
        _resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)
    return _mtcnn, _resnet


def get_face_embeddings(image_path: Path) -> list[torch.Tensor]:
    """Return a 512-d embedding tensor for every face detected in *image_path*.

    Detections with confidence below CONFIDENCE_THRESHOLD are discarded.
    Returns an empty list when no faces are found.
    """
    mtcnn, resnet = _models()
    img = Image.open(image_path).convert("RGB")

    # faces: [n, 3, 160, 160] tensor or None
    # probs: [n] array or None
    faces, probs = mtcnn(img, return_prob=True)

    if faces is None:
        return []

    mask = probs.astype(float) >= CONFIDENCE_THRESHOLD
    faces = faces[mask]

    if len(faces) == 0:
        return []

    with torch.no_grad():
        embeddings = resnet(faces.to(device))  # [n, 512]

    return [embeddings[i].cpu() for i in range(len(embeddings))]
