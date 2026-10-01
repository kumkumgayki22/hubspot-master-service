import os
import datetime
import logging
from typing import Optional, Dict, Any, List
from minio import Minio
from minio.error import S3Error
from app.config import settings

logger = logging.getLogger("hubspot_master_service.minio")


class MinIOStorageClient:
    """
    MinIO object storage client for uploading normalized parquet files.
    Enforces the storage key partitioning scheme:
    hubspot/{table_name}/glynac_organization_id={org_id}/processing_date={date}/{table_name}.parquet
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        secure: Optional[bool] = None,
        bucket_name: Optional[str] = None
    ):
        self.endpoint = endpoint or settings.MINIO_ENDPOINT
        self.access_key = access_key or settings.MINIO_ACCESS_KEY
        self.secret_key = secret_key or settings.MINIO_SECRET_KEY
        self.secure = secure if secure is not None else settings.MINIO_SECURE
        self.bucket_name = bucket_name or settings.MINIO_BUCKET

        self._client: Optional[Minio] = None
        self._init_client()

    def _init_client(self):
        try:
            self._client = Minio(
                endpoint=self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure
            )
        except Exception as exc:
            logger.warning(f"Failed to initialize MinIO client instance: {exc}")
            self._client = None

    def ensure_bucket_exists(self) -> bool:
        if not self._client:
            return False
        try:
            found = self._client.bucket_exists(self.bucket_name)
            if not found:
                self._client.make_bucket(self.bucket_name)
                logger.info(f"Created MinIO bucket: '{self.bucket_name}'")
            return True
        except Exception as exc:
            logger.error(f"Error ensuring MinIO bucket '{self.bucket_name}' exists: {exc}")
            return False

    @staticmethod
    def build_object_key(table_name: str, organization_id: str, processing_date: Optional[str] = None) -> str:
        """
        Builds object key adhering to key partitioning scheme:
        hubspot/{table_name}/glynac_organization_id={org_id}/processing_date={date}/{table_name}.parquet
        """
        date_str = processing_date or datetime.date.today().isoformat()
        return f"hubspot/{table_name}/glynac_organization_id={organization_id}/processing_date={date_str}/{table_name}.parquet"

    def upload_file(
        self,
        file_path: str,
        table_name: str,
        organization_id: str,
        processing_date: Optional[str] = None,
        content_type: str = "application/octet-stream"
    ) -> Dict[str, Any]:
        """
        Uploads a local file to MinIO using the partitioning scheme.
        Returns metadata dict with object_key, bucket, size, etc.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found for upload: {file_path}")

        file_size = os.path.getsize(file_path)
        object_key = self.build_object_key(
            table_name=table_name,
            organization_id=organization_id,
            processing_date=processing_date
        )

        if not self.ensure_bucket_exists():
            raise RuntimeError(f"MinIO bucket '{self.bucket_name}' is unavailable or client connection failed.")

        try:
            result = self._client.fput_object(
                bucket_name=self.bucket_name,
                object_name=object_key,
                file_path=file_path,
                content_type=content_type
            )
            logger.info(f"Successfully uploaded {file_path} to s3://{self.bucket_name}/{object_key} (etag: {result.etag})")
            return {
                "success": True,
                "bucket": self.bucket_name,
                "object_key": object_key,
                "file_size": file_size,
                "etag": result.etag,
                "uploaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }
        except S3Error as exc:
            logger.error(f"S3 Error uploading to MinIO: {exc}")
            raise RuntimeError(f"MinIO upload failed: {exc}")
        except Exception as exc:
            logger.error(f"Unexpected error uploading to MinIO: {exc}")
            raise RuntimeError(f"MinIO upload error: {exc}")
