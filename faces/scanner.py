"""Face detection and embedding extraction."""

from pathlib import Path
from typing import Optional

import numpy as np
import torch
import torchvision.transforms as T
from facenet_pytorch import InceptionResnetV1
from PIL import Image
from retinaface.pre_trained_models import get_model

CONFIDENCE_THRESHOLD = 0.7  # RetinaFace confidence (0–1)
FACE_MARGIN = 20             # extra pixels added around each bounding box

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Models are loaded once on first use.
_detector = None
_resnet: Optional[InceptionResnetV1] = None

# Matches the normalisation that MTCNN applied before: maps [0, 1] → [−1, 1].
_face_transform = T.Compose([
    T.Resize((160, 160)),
    T.ToTensor(),
    T.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
])


def _models():
    global _detector, _resnet
    if _detector is None:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            _detector = get_model("resnet50_2020-07-20", max_size=1280, device=str(device))
            _detector.eval()
            _resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)
    return _detector, _resnet


def _crop_face(img: Image.Image, bbox: list[int]) -> Image.Image:
    w, h = img.size
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - FACE_MARGIN)
    y1 = max(0, y1 - FACE_MARGIN)
    x2 = min(w, x2 + FACE_MARGIN)
    y2 = min(h, y2 + FACE_MARGIN)
    return img.crop((x1, y1, x2, y2))


def get_face_embeddings(image_path: Path) -> list[torch.Tensor]:
    """Return a 512-d embedding tensor for every face detected in *image_path*.

    Detections with confidence below CONFIDENCE_THRESHOLD are discarded.
    Returns an empty list when no faces are found.
    """
    detector, resnet = _models()
    img = Image.open(image_path).convert("RGB")
    annotations = detector.predict_jsons(
        np.array(img), confidence_threshold=CONFIDENCE_THRESHOLD
    )

    # predict_jsons returns [{"bbox": [], "score": -1, ...}] when nothing is found.
    faces_found = [a for a in annotations if a["bbox"]]
    if not faces_found:
        return []

    crops = torch.stack([
        _face_transform(_crop_face(img, a["bbox"]))
        for a in faces_found
    ])  # [n, 3, 160, 160]

    with torch.no_grad():
        embeddings = resnet(crops.to(device))  # [n, 512]

    return [embeddings[i].cpu() for i in range(len(embeddings))]
