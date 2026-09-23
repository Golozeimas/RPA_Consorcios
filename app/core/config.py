from dataclasses import dataclass, field
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_path: Path = ROOT / "data" / "consultas.sqlite3"
    browser_timeout_ms: int = 30000
    query_timeout_seconds: int = 120
    duplicate_seconds: int = 30
    headless: bool = True
    http_timeout_seconds: int = 30
    whatsapp_token: str = field(default="", repr=False)
    whatsapp_phone_number_id: str = ""
    whatsapp_api_version: str = ""

    def __post_init__(self) -> None:
        if min(self.browser_timeout_ms, self.query_timeout_seconds, self.duplicate_seconds, self.http_timeout_seconds) <= 0:
            raise ValueError("Os tempos de configuração devem ser positivos.")
        credenciais = (self.whatsapp_token, self.whatsapp_phone_number_id, self.whatsapp_api_version)
        if any(credenciais) and not all(credenciais):
            raise ValueError("Configure todas as variáveis WHATSAPP ou deixe todas vazias.")
        if self.whatsapp_phone_number_id and not re.fullmatch(r"[0-9]+", self.whatsapp_phone_number_id):
            raise ValueError("WHATSAPP_PHONE_NUMBER_ID deve ser numérico.")
        if self.whatsapp_api_version and not re.fullmatch(r"v[0-9]+\.0", self.whatsapp_api_version):
            raise ValueError("WHATSAPP_API_VERSION deve seguir o formato vNN.0.")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        headless = (os.getenv("BROWSER_HEADLESS") or "true").lower()
        if headless not in {"true", "false"}:
            raise ValueError("BROWSER_HEADLESS deve ser true ou false.")
        return cls(
            database_path=Path(os.getenv("DATABASE_PATH") or ROOT / "data" / "consultas.sqlite3"),
            browser_timeout_ms=int(os.getenv("BROWSER_TIMEOUT_MS") or "30000"),
            query_timeout_seconds=int(os.getenv("QUERY_TIMEOUT_SECONDS") or "120"),
            duplicate_seconds=int(os.getenv("DUPLICATE_SECONDS") or "30"),
            headless=headless == "true",
            http_timeout_seconds=int(os.getenv("HTTP_TIMEOUT_SECONDS") or "30"),
            whatsapp_token=os.getenv("WHATSAPP_ACCESS_TOKEN") or "",
            whatsapp_phone_number_id=os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "",
            whatsapp_api_version=os.getenv("WHATSAPP_API_VERSION") or "",
        )
