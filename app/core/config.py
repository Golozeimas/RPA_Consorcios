from dataclasses import dataclass
import os
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

    def __post_init__(self) -> None:
        if min(self.browser_timeout_ms, self.query_timeout_seconds, self.duplicate_seconds) <= 0:
            raise ValueError("Os tempos de configuração devem ser positivos.")

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
        )
