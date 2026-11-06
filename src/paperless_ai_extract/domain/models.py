"""Domain value objects. No I/O, no framework dependencies."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Item:
    """A taxonomy object (correspondent, document type, storage path, tag)."""
    id: int
    name: str
    owner: int | None = None


@dataclass
class Taxonomy:
    correspondents: list[Item] = field(default_factory=list)
    document_types: list[Item] = field(default_factory=list)
    storage_paths: list[Item] = field(default_factory=list)
    tags: list[Item] = field(default_factory=list)
    custom_fields: list[dict] = field(default_factory=list)

    def custom_field(self, name: str) -> dict | None:
        return next((f for f in self.custom_fields if f["name"] == name), None)

    def name_of(self, kind: str, object_id: int | None) -> str | None:
        if object_id is None:
            return None
        for item in getattr(self, kind):
            if item.id == object_id:
                return item.name
        return f"#{object_id}"


@dataclass
class DocumentSnapshot:
    id: int
    title: str = ""
    original_file_name: str | None = None
    correspondent: int | None = None
    document_type: int | None = None
    storage_path: int | None = None
    created: str | None = None
    tags: list[int] = field(default_factory=list)
    content: str = ""
    custom_fields: dict[int, object] = field(default_factory=dict)


@dataclass
class Extraction:
    kind: str
    title: str
    correspondent: str | None
    document_type: str | None
    authors: list[str] = field(default_factory=list)
    publication_year: int | None = None
    addressee_text: str = ""
    recipient: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Extraction":
        return cls(**data)


@dataclass
class Candidate:
    """A usable value derived from the extraction, with its evidence status."""
    field: str
    value: object                           # API value; None when it must be created
    display: str
    create: tuple[str, str] | None = None   # (taxonomy endpoint, name)
    verified: bool = True
    reason: str = ""
    fallback: object = None                 # safe value to fill when unverified
    fallback_display: str = ""


@dataclass
class Change:
    field: str
    action: str                             # "fill" | "propose"
    current: object                         # value seen when planning
    current_display: str
    value: object
    display: str
    create: tuple[str, str] | None = None
    verified: bool = True
    reason: str = ""
    expect: object = None                   # value required when a proposal is applied

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Change":
        data = dict(data)
        if data.get("create"):
            data["create"] = tuple(data["create"])
        return cls(**data)


@dataclass
class Plan:
    doc_id: int
    mode: str                               # "first_run" | "rerun"
    kind: str
    changes: list[Change] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    review: bool = False

    @property
    def fills(self) -> list[Change]:
        return [c for c in self.changes if c.action == "fill"]

    @property
    def proposals(self) -> list[Change]:
        return [c for c in self.changes if c.action == "propose"]

    def to_dict(self) -> dict:
        return asdict(self)
