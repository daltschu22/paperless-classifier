from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    paperless_url: str
    paperless_token: str
    typesafe_key: str
    data_dir: Path
    origin: str = "http://127.0.0.1:8098"
    paperless_public_url: str = ""
    openai_key: str = ""
    generative_model: str = "gpt-5.6-sol"
    jev_model: str = "jev-1.13.0"
    max_characters: int = 60000
    max_pages: int = 8
    max_file_bytes: int = 20 * 1024 * 1024

    @classmethod
    def from_env(cls):
        required = ("PAPERLESS_URL", "PAPERLESS_API_TOKEN", "TYPESAFE_API_KEY")
        if any(not os.environ.get(key) for key in required):
            raise RuntimeError("Set PAPERLESS_URL, PAPERLESS_API_TOKEN, and TYPESAFE_API_KEY.")
        origin = os.environ.get("APP_ORIGIN", "http://127.0.0.1:8098").rstrip("/")
        base = os.environ["PAPERLESS_URL"].rstrip("/")
        for value in (origin, base):
            parsed = urlsplit(value)
            if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
                raise RuntimeError("Invalid application or Paperless URL.")
        return cls(base, os.environ["PAPERLESS_API_TOKEN"], os.environ["TYPESAFE_API_KEY"],
                   Path(os.environ.get("DATA_DIR", "private/app-data")), origin,
                   os.environ.get("PAPERLESS_PUBLIC_URL", base).rstrip("/"),
                   os.environ.get("OPENAI_API_KEY", ""),
                   os.environ.get("GENERATIVE_MODEL", "gpt-5.6-sol"),
                   os.environ.get("JEV_MODEL", "jev-1.13.0"))


class AppError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message
