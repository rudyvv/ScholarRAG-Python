"""MinIO client wrapper.

Provides a minimal ``MinioClient`` wrapper and a factory helper
for application startup.  The underlying ``minio.Minio`` is
synchronous; this module does *not* add async wrappers — it is
intended for one-time startup initialisation.
"""

import logging

from minio import Minio

from app.config import Settings

logger = logging.getLogger(__name__)


class MinioClient:
    """Thin wrapper around ``minio.Minio`` with bucket auto-creation."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
    ) -> None:
        self._client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket: str | None = None

    def ensure_bucket(self, bucket_name: str) -> None:
        """Create the bucket if it does not already exist."""
        if not self._client.bucket_exists(bucket_name):
            self._client.make_bucket(bucket_name)
            logger.info("MinIO bucket '%s' created", bucket_name)
        self._bucket = bucket_name

    @property
    def client(self) -> Minio:
        """Return the raw ``Minio`` instance."""
        return self._client

    @property
    def bucket(self) -> str | None:
        """Return the configured bucket name, or ``None``."""
        return self._bucket


def init_minio(settings: Settings) -> MinioClient | None:
    """Create and initialise a ``MinioClient`` from application settings.

    Returns ``None`` if the connection fails (e.g. MinIO is not running),
    so callers can degrade gracefully during development.
    """
    try:
        client = MinioClient(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        client.ensure_bucket(settings.MINIO_BUCKET)
    except Exception:
        logger.warning("MinIO initialization failed — skip or check config")
        return None
    else:
        logger.info("MinIO initialized at %s", settings.MINIO_ENDPOINT)
        return client
