"""运行配置：全部从环境变量 / .env 读取，密钥不落代码。"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "学习小岛 后端"
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'xiaodao.db').as_posix()}"
    data_dir: Path = BASE_DIR / "data"

    # 匿名访客令牌签名密钥：上线必须换成随机的（.env 里配）
    token_secret: str = "dev-only-secret-please-change"

    # 上传限制
    max_file_mb: int = 100
    max_pages: int = 500
    allowed_ext: str = "pdf,pptx,docx,md,txt"

    # 接口限流（每令牌每分钟）
    rate_limit_per_minute: int = 120

    # CORS 白名单，逗号分隔，* 表示开发期全放开
    allowed_origins: str = "*"

    # MVP 默认在进程内跑任务轮询；生产建议关掉、单独起 worker.py
    auto_worker: bool = True

    # 扫描页渲染 / OCR
    render_dpi: int = 150
    ocr_dpi: int = 200          # 正式 OCR 的分辨率
    ocr_probe_dpi: int = 110    # 找目录页时的低分辨率试探
    toc_probe_from: int = 3
    toc_probe_to: int = 16
    # 扫描书按需生成：一次最多生成多少节（全书后台慢慢来；0 表示不限）
    max_sections_generate: int = 6
    ocr_engine: str = "rapidocr"

    # AI：默认 mock（离线假数据），配好密钥后改 api 即可切真模型，代码不用动
    ai_provider: str = "mock"  # mock | api
    ai_base_url: str = "https://api.example.com/v1"
    ai_api_key: str = ""
    ai_model: str = "large-model"
    ai_model_cheap: str = "small-model"
    ai_timeout: int = 120

    @property
    def allowed_ext_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_ext.split(",") if e.strip()}

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    def ensure_dirs(self) -> None:
        for sub in ("uploads", "pages"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)


settings = Settings()
