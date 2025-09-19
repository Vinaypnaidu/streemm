# apps/api/schemas.py
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime

class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class UserOut(BaseModel):
    id: str
    email: str

class Ok(BaseModel):
    ok: bool

class PresignRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int

class PresignResponse(BaseModel):
    video_id: str
    raw_key: str
    put_url: str
    headers: Dict[str, str]

class FinalizeVideoRequest(BaseModel):
    video_id: str
    raw_key: str
    original_filename: str
    checksum_sha256: Optional[str] = None
    title: Optional[str] = ""
    description: Optional[str] = ""

class VideoAssetOut(BaseModel):
    id: str
    kind: str
    label: str
    storage_key: str
    meta: Optional[Dict[str, Any]] = None
    public_url: Optional[str] = None

class VideoOut(BaseModel):
    id: str
    status: str
    original_filename: str
    title: str
    description: str
    created_at: datetime
    thumbnail_public_url: Optional[str] = None

class VideoDetail(BaseModel):
    id: str
    status: str
    original_filename: str
    title: str
    description: str
    storage_key_raw: str
    duration_seconds: Optional[str] = None
    checksum_sha256: Optional[str] = None
    probe: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    assets: List[VideoAssetOut] = []

class PublicVideoDetail(BaseModel):
    id: str
    status: str
    original_filename: str
    title: str
    description: str
    duration_seconds: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    assets: List[VideoAssetOut] = []

class PaginatedVideos(BaseModel):
    items: List[VideoOut]
    next_offset: Optional[int] = None