import hashlib
import json
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewTag(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    definition: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=500)


class Enrichment(StrictModel):
    title: str = Field(max_length=160)
    new_tags: list[NewTag] = Field(max_length=3)


class VisionText(StrictModel):
    text: str = Field(max_length=60000)
    legible: bool


class Options(StrictModel):
    enrich: bool = True
    vision_fallback: bool = True
    force_vision: bool = False


class QueueRequest(Options):
    document_ids: list[int] = Field(min_length=1, max_length=10)


class Approval(StrictModel):
    tag_ids: list[int] = Field(default_factory=list, max_length=128)
    document_type: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    new_tag_indices: list[int] = Field(default_factory=list, max_length=3)


class Intake(StrictModel):
    enabled: bool = False
    tag_id: int | None = None
    enrich: bool = True
    vision_fallback: bool = True


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def text_hash(doc):
    return digest({"id": doc["id"], "content": doc.get("content", ""), "checksum": doc.get("checksum")})


def tag_key(name):
    return re.sub(r"[\W_]+", "-", unicodedata.normalize("NFKC", name).casefold()).strip("-")


def metadata(doc):
    return {"title": doc.get("title", ""), "document_type": doc.get("document_type"),
            "tags": sorted(doc.get("tags", []))}
