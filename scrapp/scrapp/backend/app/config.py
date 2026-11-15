from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "scrapp"

    # Sign-up gate. When set, POST /auth/register must send this code (accounts can use the 3D budget, so a public
    # URL must not be open to anyone). Empty = open sign-up (local development).
    invite_code: str = ""

    jwt_secret: str = "change-me"
    jwt_ttl_hours: int = 24 * 30
    file_url_ttl_hours: int = 24 * 7

    # Base URL phones and browsers use to reach this API (signed file URLs, web viewer links).
    public_base_url: str = "http://localhost:8000"

    # Segmentation: "sam3" (GPU server, default), "grabcut" (CPU dev fallback, no SAM).
    segmenter: str = "sam3"
    # Local SAM 3 image checkpoint (sam3.pt). Empty = download facebook/sam3 from Hugging Face.
    sam3_checkpoint: str = ""
    # Text-prompt score cutoff. 0.15 recovered a clock that 0.4 missed on the real-photo eval.
    sam3_confidence: float = 0.15
    # With no spoken noun, these concrete nouns are tried as text prompts (SAM 3 cuts whole objects for
    # them; abstract words like "object" find nothing). Comma separated; ~0.05 s each.
    sam3_vocab: str = (
        "laptop,phone,computer mouse,keyboard,monitor,tv,remote control,headphones,camera,bottle,can,cup,mug,"
        "glass,bowl,plate,book,bag,backpack,suitcase,box,wallet,keys,pen,scissors,toy,stuffed animal,teddy bear,"
        "plant,flower,food,fruit,banana,apple,orange,pizza,sandwich,cake,drink,sign,painting,clock,lamp,vase,"
        "shoe,hat,sunglasses,umbrella,person,dog,cat,bird,horse,sheep,cow,zebra,giraffe,elephant,bear,car,"
        "bicycle,motorcycle,boat,chair,couch,toaster,microwave,ball,skateboard,kite"
    )
    sam_device: str = "cuda"
    sam_max_side: int = 1536
    stickers_per_capture: int = 4

    # Shared key for the web app's bridge (routers/webapp.py). Empty = the bridge is off.
    webapp_key: str = ""

    # Hunt matching thresholds (SIFT + RANSAC homography)
    match_min_inliers: int = 25
    match_min_inlier_ratio: float = 0.2
    hunt_default_radius_m: float = 150.0

    # Hunt appearance matching (DINOv2 embeddings), tried only when SIFT finds nothing. Optional: if the model cannot be
    # loaded the hunt silently stays SIFT-only. CPU by default so it never competes with SAM for the GPU.
    embed_enabled: bool = True
    embed_model: str = "vit_small_patch14_dinov2.lvd142m"
    embed_device: str = "cpu"
    embed_min_score: float = 0.35  # best view-vs-target cosine similarity (calibrated: 0 of 17 false accepts)
    embed_margin: float = 0.05     # lead over the runner-up item
    embed_standout: float = 0.08   # best view minus the mean over views (the distractor baseline)

    meshy_api_key: str = ""
    meshy_base_url: str = "https://api.meshy.ai/openapi"
    # Model: "meshy-6-lite" is the cheap one (text preview 5 credits, image+texture 15); "latest" (Meshy 7.1) looks
    # better but costs 20 + 10 for text and 30 for image. Check docs.meshy.ai/en/api/pricing before switching.
    meshy_ai_model: str = "meshy-6-lite"
    # PBR adds metallic/roughness/normal maps: bigger GLBs for a phone WebView, little visible gain here.
    meshy_enable_pbr: bool = False
    # Triangles per model. Phones render several models in a collage; Meshy's default 30000 is more than needed.
    meshy_target_polycount: int = 15000
    # The API is public, and every job spends the owner's credits: cap each user.
    meshy_max_active_per_user: int = 2
    meshy_daily_limit_per_user: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
