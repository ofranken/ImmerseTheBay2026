from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=24, pattern=r"^[a-zA-Z0-9_.]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = None
    invite_code: str | None = Field(default=None, max_length=64)


class LoginIn(BaseModel):
    username_or_email: str
    password: str


class TokenOut(BaseModel):
    token: str
    user: dict


class CaptureMeta(BaseModel):
    """Metadata the phone sends alongside the original photo."""
    captured_at: str | None = None  # ISO-8601 from the phone clock
    lat: float | None = None
    lng: float | None = None
    accuracy_m: float | None = None
    altitude_m: float | None = None
    place_name: str | None = None
    trigger: Literal["voice", "button", "app", "import", "voice_invocation"] = "app"
    transcript: str | None = None
    prompt: str | None = None  # "scrap that <noun>" -> noun (used by a SAM 3 backend)
    device: str | None = None


class PointIn(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class StickerPatch(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    starred: bool | None = None


AnchorMode = Literal["none", "surface", "object", "image", "geo"]
Animation = Literal["none", "wiggle", "bob", "spin", "pop"]


class Anchor(BaseModel):
    mode: AnchorMode = "surface"
    object_class: str | None = None  # COCO class name for mode=object, e.g. "apple"
    animation: Animation = "wiggle"
    size_m: float = Field(default=0.12, gt=0.01, le=3)
    lat: float | None = None
    lng: float | None = None


class ShareIn(BaseModel):
    to_user_ids: list[str]
    kind: Literal["sticker", "collage", "hunt", "mesh"]
    item_id: str
    anchor: Anchor | None = None
    message: str | None = Field(default=None, max_length=280)


class SceneBackground(BaseModel):
    """scene.background: the backdrop behind a collage. Absent = the default paper."""
    type: Literal["color", "paper", "gradient", "photo"]
    value: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")        # color
    colors: list[str] | None = Field(default=None, min_length=2, max_length=4)    # gradient
    angle: float | None = Field(default=None, ge=0, le=360)                       # gradient, CSS degrees (180 = top to bottom)
    ref_id: str | None = Field(default=None, max_length=40)                       # photo: one of the owner's captures


class CollageIn(BaseModel):
    title: str = "Untitled collage"
    scene: dict  # see docs/ARCHITECTURE.md "Collage scene format"


class MeshTextIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=600)  # Meshy allows 800


class MeshFromStickerIn(BaseModel):
    sticker_id: str


class HuntItemIn(BaseModel):
    sticker_id: str
    title: str | None = None
    hint: str | None = Field(default=None, max_length=200)
    radius_m: float | None = None
    animation: Animation = "pop"


class HuntIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    items: list[HuntItemIn] = Field(min_length=1, max_length=50)


class FriendRequestIn(BaseModel):
    username: str
