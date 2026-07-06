from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_NAME: str = "Paismart RAG"
    DEBUG: bool = False
    SECRET_KEY: str = "change-me-in-production-must-be-at-least-32-bytes"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days

    # MySQL
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "paismart"
    MYSQL_PASSWORD: str = "paismart123"
    MYSQL_DATABASE: str = "paismart"

    @property
    def DATABASE_URL(self) -> str:  # noqa: N802
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            "?charset=utf8mb4"
        )

    # Redis
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "redis123"

    @property
    def REDIS_URL(self) -> str:  # noqa: N802
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # RabbitMQ (Celery broker)
    RABBITMQ_USER: str = "paismart"
    RABBITMQ_PASSWORD: str = "paismart123"
    RABBITMQ_HOST: str = "127.0.0.1"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_VHOST: str = "paismart"

    @property
    def CELERY_BROKER_URL(self) -> str:  # noqa: N802
        return (
            f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}"
            f"@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}/{self.RABBITMQ_VHOST}"
        )

    # CORS
    CORS_ORIGINS: str = "*"

    # MinIO
    MINIO_ENDPOINT: str = "127.0.0.1:19000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "paismart-documents"
    MINIO_SECURE: bool = False

    # Elasticsearch
    ELASTICSEARCH_HOST: str = "127.0.0.1"
    ELASTICSEARCH_PORT: int = 9200

    @property
    def ELASTICSEARCH_URL(self) -> str:  # noqa: N802
        return f"http://{self.ELASTICSEARCH_HOST}:{self.ELASTICSEARCH_PORT}"

    # Milvus
    MILVUS_HOST: str = "127.0.0.1"
    MILVUS_PORT: int = 19530

    # --- LLM / Embedding (SiliconFlow) ---
    LLM_API_BASE_URL: str = "https://api.siliconflow.cn/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "Qwen/Qwen3-8B"

    EMBEDDING_API_BASE_URL: str = "https://api.siliconflow.cn/v1/embeddings"
    EMBEDDING_API_KEY: str = ""
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024

    # Reranker (SiliconFlow, separate — not from DB ModelProviderConfig)
    RERANKER_API_BASE_URL: str = "https://api.siliconflow.cn/v1"
    RERANKER_API_KEY: str = ""
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # Invite codes
    DEFAULT_INVITE_CODES: str = "PRE_INVITE_001,PRE_INVITE_002"

    # Admin bootstrap
    ADMIN_USERNAME: str = "admin"
    ADMIN_EMAIL: str = "admin@paismart.com"
    ADMIN_PASSWORD: str = "Admin123!"

    @property
    def default_invite_codes_list(self) -> list[str]:
        """Return default invite codes as a list, stripping whitespace."""
        return [c.strip() for c in self.DEFAULT_INVITE_CODES.split(",") if c.strip()]


settings = Settings()
