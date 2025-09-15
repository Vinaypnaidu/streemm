# apps/api/schemas.py
from pydantic import BaseModel
from typing import Dict

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