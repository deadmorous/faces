"""Pydantic request/response schemas for the faces web API."""

from typing import Optional

from pydantic import BaseModel


# --- Image / face helpers ---

class FaceSample(BaseModel):
    img_url: str


# --- Clusters ---

class ClusterSummary(BaseModel):
    id: int
    name: Optional[str]
    size: int
    sample_faces: list[FaceSample]


class FaceDetail(BaseModel):
    md5: str
    bbox: list[int]
    score: float
    sticky_name: Optional[str]
    img_url: str
    photo_url: str
    photo_path: str
    photo_detail_url: str


class ClusterDetail(BaseModel):
    id: int
    name: Optional[str]
    size: int
    faces: list[FaceDetail]


class ClusterPatchRequest(BaseModel):
    name: str
    stick: bool = False


class ClusterPatchResponse(BaseModel):
    cluster_id: int
    name: str
    faces_updated: int


# --- People ---

class Person(BaseModel):
    name: str
    face_count: int
    photo_count: int


class PersonPhoto(BaseModel):
    md5: str
    path: str
    exif_date: Optional[float]
    photo_url: str
    photo_detail_url: str
    face_bboxes: list[list[int]]


class PersonDetail(BaseModel):
    name: str
    photos: list[PersonPhoto]


# --- Photos ---

class PhotoSummary(BaseModel):
    md5: str
    path: str
    face_count: int
    exif_date: Optional[float]
    photo_url: str


class PhotoList(BaseModel):
    total: int
    photos: list[PhotoSummary]


class PhotoFaceDetail(BaseModel):
    bbox: list[int]
    score: float
    sticky_name: Optional[str]
    cluster_id: Optional[int]
    img_url: str
    cluster_url: Optional[str]


class PhotoDetail(BaseModel):
    md5: str
    path: str
    exif_date: Optional[float]
    exif_orientation: int = 1
    photo_url: str
    faces: list[PhotoFaceDetail]


# --- Face label ---

class FaceLabelRequest(BaseModel):
    name: Optional[str]


# --- Classify ---

class ClassifyFace(BaseModel):
    md5: str
    bbox: list[int]
    dist: float
    img_url: str
    photo_url: str
    photo_path: str


class ClassifyGroup(BaseModel):
    person: str
    avg_dist: float
    faces: list[ClassifyFace]


class UnmatchedFace(BaseModel):
    md5: str
    bbox: list[int]
    img_url: str
    photo_url: str


class ClassifyCandidates(BaseModel):
    eps: float
    total_groups: int
    groups: list[ClassifyGroup]
    unmatched: list[UnmatchedFace]


class FaceLabelItem(BaseModel):
    md5: str
    bbox: list[int]
    name: Optional[str]


class ClassifyLabelsResponse(BaseModel):
    labeled: int


# --- Clusterize ---

class ClusterizeRequest(BaseModel):
    reset: bool = False
    threshold: Optional[float] = None


class ClusterizeResponse(BaseModel):
    clusters_created: int
    auto_named: int
    must_link_pairs: int
    cannot_link_pairs: int
