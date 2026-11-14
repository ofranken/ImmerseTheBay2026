from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "scrapp"

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
    sam_device: str = "cuda"
    sam_max_side: int = 1536
    stickers_per_capture: int = 4

    # Hunt matching thresholds (SIFT + RANSAC homography)
    match_min_inliers: int = 25
    match_min_inlier_ratio: float = 0.2
    hunt_default_radius_m: float = 150.0

    meshy_api_key: str = ""
    meshy_base_url: str = "https://api.meshy.ai/openapi"


@lru_cache
def get_settings() -> Settings:
    return Settings()
