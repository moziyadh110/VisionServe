"""Image storage in a local S3-compatible server (RustFS) or AWS S3, through boto3.

Postgres keeps only metadata and the object key; the bytes live here. Object
stores are built for large blobs (cheap, no table bloat, served directly to
clients via pre-signed URLs), while a database is built for small, queryable rows.

boto3 is synchronous, so callers run these methods with asyncio.to_thread.
"""

from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import Settings


class ObjectStore(Protocol):
    def ensure_bucket(self) -> None: ...
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def presigned_url(self, key: str, expires_s: int) -> str: ...


class S3Storage:
    def __init__(self, settings: Settings):
        self.bucket = settings.s3_bucket
        self.region = settings.s3_region
        common = dict(
            # Empty values mean "not set": on AWS, boto3 then uses the VM's IAM role.
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url or None, **common)
        # Pre-signed URLs embed the host they were signed for. Inside Docker the API
        # reaches storage as http://storage:9000, but a browser needs http://localhost:9000.
        public = settings.s3_public_endpoint_url or settings.s3_endpoint_url or None
        self.signer = boto3.client("s3", endpoint_url=public, **common)

    def ensure_bucket(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            kwargs = {}
            if self.region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
            self.client.create_bucket(Bucket=self.bucket, **kwargs)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def presigned_url(self, key: str, expires_s: int) -> str:
        """A time-limited URL anyone can GET without credentials.

        The signature covers the bucket, key and expiry, so it can't be edited to
        reach another object or live longer. Signing is local; no network call.
        """
        return self.signer.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_s
        )
