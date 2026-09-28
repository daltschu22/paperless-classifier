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


class Discovery(StrictModel):
    text_readable: bool
    title: str = Field(max_length=160)
    subjects: list[NewTag] = Field(max_length=6)


class VisionText(StrictModel):
    text: str = Field(max_length=60000)
    legible: bool


class Options(StrictModel):
    enrich: bool = True
    vision_fallback: bool = True
    force_vision: bool = False


class QueueRequest(Options):
    document_ids: list[int] = Field(min_length=1, max_length=10)


class SubjectChoice(StrictModel):
    index: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    existing_tag_id: int | None = Field(default=None, gt=0)


class ExistingTag(StrictModel):
    id: int
    name: str
    definition: str = ""


class Approval(StrictModel):
    # Optional in storage for approvals made before revision binding was added.
    # Service.approve requires it on every new submission.
    proposal_revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    tag_ids: list[int] = Field(default_factory=list, max_length=128)
    document_type: int | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    new_tag_indices: list[int] = Field(default_factory=list, max_length=3)
    subject_choices: list[SubjectChoice] = Field(default_factory=list, max_length=6)


class ApprovedTag(NewTag):
    index: int = Field(ge=0)


class ApprovedChanges(Approval):
    selected_new_tags: list[ApprovedTag] | None = None
    selected_existing_tags: list[ExistingTag] = Field(default_factory=list)


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
