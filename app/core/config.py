from typing import Any, Dict, List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Project Info
    PROJECT_NAME: str = Field(default="IT Asset Lifecycle Management System (ALMS)", env="PROJECT_NAME")
    VERSION: str = Field(default="1.0.0", env="VERSION")
    API_V1_STR: str = Field(default="/api/v1", env="API_V1_STR")
    DEBUG: bool = Field(default=True, env="DEBUG")

    # Server Settings
    HOST: str = Field(default="0.0.0.0", env="HOST")
    PORT: int = Field(default=8000, env="PORT")
    WORKERS: int = Field(default=1, env="WORKERS")
    
    # Security
    SECRET_KEY: str = Field(default="your-secret-key-change-in-production", env="SECRET_KEY")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24 * 8, env="ACCESS_TOKEN_EXPIRE_MINUTES")  # 8 days
    
    # CORS Settings
    CORS_ORIGINS: List[str] = Field(default=["*"], env="CORS_ORIGINS")
    CORS_CREDENTIALS: bool = Field(default=True, env="CORS_CREDENTIALS")
    CORS_METHODS: List[str] = Field(default=["*"], env="CORS_METHODS")
    CORS_HEADERS: List[str] = Field(default=["*"], env="CORS_HEADERS")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_FORMAT: str = Field(default="%(asctime)s - %(name)s - %(levelname)s - %(message)s", env="LOG_FORMAT")
    
    # File Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    LOGS_DIR: Path = BASE_DIR / "logs"
    
    # Database Configuration
    DATABASE_URL: Optional[str] = None
    
    # MySQL Database Settings
    MYSQL_USER: str = Field(default="root", env="MYSQL_USER")
    MYSQL_PASSWORD: str = Field(default="123456", env="MYSQL_PASSWORD")
    MYSQL_HOST: str = Field(default="localhost", env="MYSQL_HOST")
    MYSQL_PORT: int = Field(default=3306, env="MYSQL_PORT")
    MYSQL_DB: str = Field(default="alms_db", env="MYSQL_DB")
    
    # Work Order System Settings
    WORK_ORDER_API_URL: str = Field(..., env="WORK_ORDER_API_URL")
    WORK_ORDER_APPID: str = Field(..., env="WORK_ORDER_APPID")
    WORK_ORDER_USERNAME: str = Field(..., env="WORK_ORDER_USERNAME")
    WORK_ORDER_CREATOR: str = Field(..., env="WORK_ORDER_CREATOR")
    WORK_ORDER_RELATED_PRODUCT: str = Field(default="spy", env="WORK_ORDER_RELATED_PRODUCT")
    WORK_ORDER_COOKIE: Optional[str] = Field(default=None, env="WORK_ORDER_COOKIE")
    
    # SLA Configuration
    DEFAULT_SLA_HOURS: int = Field(default=72, env="DEFAULT_SLA_HOURS")
    
    # Logstash Configuration
    ENABLE_LOGSTASH: bool = Field(default=False, env="ENABLE_LOGSTASH")
    LOGSTASH_HOST: str = Field(default="localhost", env="LOGSTASH_HOST")
    LOGSTASH_PORT: int = Field(default=4561, env="LOGSTASH_PORT")
    
    # Elasticsearch Configuration
    ELASTICSEARCH_HOST: str = Field(default="localhost", env="ELASTICSEARCH_HOST")
    ELASTICSEARCH_PORT: int = Field(default=9200, env="ELASTICSEARCH_PORT")
    ELASTICSEARCH_INDEX: str = Field(default="alms-logs-*", env="ELASTICSEARCH_INDEX")
    ELASTICSEARCH_USE_SSL: bool = Field(default=False, env="ELASTICSEARCH_USE_SSL")
    ELASTICSEARCH_USERNAME: Optional[str] = Field(default=None, env="ELASTICSEARCH_USERNAME")
    ELASTICSEARCH_PASSWORD: Optional[str] = Field(default=None, env="ELASTICSEARCH_PASSWORD")
    ELASTICSEARCH_API_KEY: Optional[str] = Field(default=None, env="ELASTICSEARCH_API_KEY")

    # Picture/Attachment Storage Configuration
    PICTURE_DIR: str = Field(default="/opt/aiot/images", env="PICTURE_DIR")
    PICTURE_HTTP: str = Field(default="https://download.sihua.tech/alms/images", env="PICTURE_HTTP")
    MAX_UPLOAD_SIZE: int = Field(default=10 * 1024 * 1024, env="MAX_UPLOAD_SIZE")  # 10MB
    ALLOWED_EXTENSIONS: List[str] = Field(default=["jpg", "jpeg", "png", "gif", "bmp", "webp"], env="ALLOWED_EXTENSIONS")

    # Nacos Integration
    NACOS_ENABLED: bool = Field(default=False, env="NACOS_ENABLED")
    NACOS_SERVER_ADDRESSES: List[str] | str = Field(default=["127.0.0.1:8848"], env="NACOS_SERVER_ADDRESSES")
    NACOS_NAMESPACE: str = Field(default="public", env="NACOS_NAMESPACE")
    NACOS_USERNAME: Optional[str] = Field(default=None, env="NACOS_USERNAME")
    NACOS_PASSWORD: Optional[str] = Field(default=None, env="NACOS_PASSWORD")
    NACOS_ACCESS_KEY: Optional[str] = Field(default=None, env="NACOS_ACCESS_KEY")
    NACOS_SECRET_KEY: Optional[str] = Field(default=None, env="NACOS_SECRET_KEY")
    NACOS_CONFIG_ENABLED: bool = Field(default=False, env="NACOS_CONFIG_ENABLED")
    NACOS_CONFIG_DATA_ID: str = Field(default="alms-config", env="NACOS_CONFIG_DATA_ID")
    NACOS_CONFIG_GROUP: str = Field(default="DEFAULT_GROUP", env="NACOS_CONFIG_GROUP")
    NACOS_CONFIG_POLL_INTERVAL: int = Field(default=30, env="NACOS_CONFIG_POLL_INTERVAL")
    NACOS_SERVICE_ENABLED: bool = Field(default=False, env="NACOS_SERVICE_ENABLED")
    NACOS_SERVICE_NAME: str = Field(default="alms-service", env="NACOS_SERVICE_NAME")
    NACOS_SERVICE_GROUP: str = Field(default="DEFAULT_GROUP", env="NACOS_SERVICE_GROUP")
    NACOS_SERVICE_CLUSTER: str = Field(default="DEFAULT", env="NACOS_SERVICE_CLUSTER")
    NACOS_SERVICE_IP: Optional[str] = Field(default=None, env="NACOS_SERVICE_IP")
    NACOS_SERVICE_PORT: Optional[int] = Field(default=None, env="NACOS_SERVICE_PORT")
    NACOS_HEARTBEAT_INTERVAL: int = Field(default=5, env="NACOS_HEARTBEAT_INTERVAL")
    NACOS_METADATA: Optional[Dict[str, Any]] = Field(default=None, env="NACOS_METADATA")

    @property
    def SQLALCHEMY_DATABASE_URI(self):
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )
    
    @field_validator("LOGS_DIR")
    def create_logs_dir(cls, v: Path) -> Path:
        """Create logs directory if it doesn't exist."""
        v.mkdir(parents=True, exist_ok=True)
        return v
    
    @field_validator("CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: str | List[str]) -> List[str]:
        """Parse CORS origins from string or list."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    @field_validator("NACOS_SERVER_ADDRESSES", mode="after")
    def parse_nacos_server_addresses(cls, v: List[str] | str) -> List[str]:
        """Allow comma-separated or list-based server address definitions."""
        if isinstance(v, str):
            return [addr.strip() for addr in v.split(",") if addr.strip()]
        return v

    @field_validator("NACOS_METADATA", mode="before")
    def parse_nacos_metadata(cls, v: Any) -> Optional[Dict[str, Any]]:
        """Support JSON string or key=value pairs for metadata."""
        if not v:
            return None
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                items = {}
                for pair in v.split(","):
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        items[key.strip()] = value.strip()
                return items or None
        raise ValueError("Invalid NACOS_METADATA format")
    
# Create settings instance
settings = Settings()

# Create logs directory if it doesn't exist
settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)