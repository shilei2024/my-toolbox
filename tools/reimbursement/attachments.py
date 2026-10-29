"""Bounded invoice originals; DB is durable, disk is an optional cache."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import uuid
from extensions import db
from models import ReimbursementAttachment

MAX_BYTES = 20 * 1024 * 1024
MIMES = {".pdf":"application/pdf", ".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg"}


@dataclass
class PreparedOriginal:
    name: str
    ext: str
    data: bytes
    sha256: str


def read_original(file, name_override=None):
    if not file or not file.filename:
        raise ValueError("请选择票据原件")
    name = str(name_override or file.filename).replace("\\", "/").rsplit("/", 1)[-1]
    ext = Path(name).suffix.lower()
    if ext not in MIMES or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise ValueError("请选择有效的 PDF、PNG 或 JPG 原件")
    data = file.stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("文件大小不能超过 20MB")
    valid = (ext == ".pdf" and data.startswith(b"%PDF-") or
        ext == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n") or
        ext in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff"))
    if not valid:
        raise ValueError("文件内容与格式不匹配，请选择有效的 PDF、PNG 或 JPG 原件")
    return PreparedOriginal(name, ext, data, hashlib.sha256(data).hexdigest())


def persist_original(original, owner_type, owner_id):
    duplicate = ReimbursementAttachment.query.filter_by(owner_type=owner_type, owner_id=owner_id,
        content_sha256=original.sha256).first()
    if not duplicate:
        duplicate = ReimbursementAttachment.query.filter_by(owner_type=owner_type, owner_id=owner_id,
            content_sha256=None, file_size=len(original.data), content=original.data).first()
    if duplicate:
        duplicate.content_sha256 = original.sha256
        db.session.flush()
        return duplicate, False
    attachment = ReimbursementAttachment(owner_type=owner_type, owner_id=owner_id,
        stored_name=uuid.uuid4().hex[:12]+original.ext, original_name=original.name,
        mime_type=MIMES[original.ext], file_size=len(original.data), content=original.data,
        content_sha256=original.sha256)
    db.session.add(attachment)
    db.session.flush()
    return attachment, True
