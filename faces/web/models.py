"""Pydantic request/response schemas for the faces web API."""

from typing import Optional

from pydantic import BaseModel


# --- Image / face helpers ---

class FaceSample(BaseModel):
    img_url: str


class FaceDetail(BaseModel):
    md5: str
    bbox: list[int]
    score: float
    sticky_name: Optional[str]
    img_url: str
    photo_url: str
    photo_path: str
    photo_detail_url: str


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
    total: int
    page: int
    page_size: int
    photos: list[PersonPhoto]


class PersonFaceItem(BaseModel):
    md5: str
    bbox: list[int]
    img_url: str
    photo_path: str


class PersonFacesPage(BaseModel):
    name: str
    total: int
    page: int
    page_size: int
    faces: list[PersonFaceItem]


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
    md5: str
    bbox: list[int]
    score: float
    sticky_name: Optional[str]
    img_url: str


class PhotoDetail(BaseModel):
    md5: str
    path: str
    exif_date: Optional[float]
    exif_orientation: int = 1
    photo_url: str
    faces: list[PhotoFaceDetail]


# --- Similar faces ---

class SimilarFace(BaseModel):
    md5: str
    bbox: list[int]
    dist: float
    name: Optional[str]
    img_url: str
    photo_path: str


class SimilarFacesResponse(BaseModel):
    seed: SimilarFace
    faces: list[SimilarFace]


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


