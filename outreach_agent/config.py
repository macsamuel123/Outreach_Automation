import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class Settings:
    apify_api_token: str
    hunter_api_key: str
    deepseek_api_key: str
    email_address: str
    email_app_password: str


def load_config(path: Path = Path("config.yaml")) -> dict:
    """Load YAML config file."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings() -> Settings:
    """Load .env file and extract required settings."""
    load_dotenv()

    required_vars = [
        "APIFY_API_TOKEN",
        "HUNTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "EMAIL_ADDRESS",
        "EMAIL_APP_PASSWORD",
    ]

    missing = [var for var in required_vars if not os.environ.get(var)]
    if missing:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Please set them in .env file"
        )

    return Settings(
        apify_api_token=os.environ["APIFY_API_TOKEN"],
        hunter_api_key=os.environ["HUNTER_API_KEY"],
        deepseek_api_key=os.environ["DEEPSEEK_API_KEY"],
        email_address=os.environ["EMAIL_ADDRESS"],
        email_app_password=os.environ["EMAIL_APP_PASSWORD"],
    )
