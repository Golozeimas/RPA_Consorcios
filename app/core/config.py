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
    twilio_account_sid: str = field(default="", repr=False)
    twilio_auth_token: str = field(default="", repr=False)
    twilio_whatsapp_from: str = ""

    def __post_init__(self) -> None:
        if min(self.browser_timeout_ms, self.query_timeout_seconds, self.duplicate_seconds, self.http_timeout_seconds) <= 0:
            raise ValueError("Os tempos de configuração devem ser positivos.")
        credenciais = (self.twilio_account_sid, self.twilio_auth_token, self.twilio_whatsapp_from)
        if any(credenciais) and not all(credenciais):
            raise ValueError("Configure TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN e TWILIO_WHATSAPP_FROM juntos.")
        if self.twilio_account_sid and not re.fullmatch(r"AC[0-9a-fA-F]{32}", self.twilio_account_sid):
            raise ValueError("TWILIO_ACCOUNT_SID deve ser um Account SID válido.")
        if self.twilio_whatsapp_from and not re.fullmatch(r"whatsapp:\+[1-9][0-9]{7,14}", self.twilio_whatsapp_from):
            raise ValueError("TWILIO_WHATSAPP_FROM deve seguir o formato whatsapp:+DDINUMERO.")

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
            twilio_account_sid=(os.getenv("TWILIO_ACCOUNT_SID") or "").strip(),
            twilio_auth_token=(os.getenv("TWILIO_AUTH_TOKEN") or "").strip(),
            twilio_whatsapp_from=(os.getenv("TWILIO_WHATSAPP_FROM") or "").strip(),
        )
