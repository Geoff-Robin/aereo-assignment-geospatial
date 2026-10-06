import os
import time

import boto3
from botocore.exceptions import ConnectionClosedError, EndpointConnectionError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Wait for S3-compatible storage and create the upload bucket."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wait-seconds",
            type=float,
            default=60.0,
            help="Maximum number of seconds to wait for object storage.",
        )

    def handle(self, *args, **options):
        endpoint_url = os.environ.get("S3_ENDPOINT_URL")
        access_key = os.environ.get("S3_ACCESS_KEY")
        secret_key = os.environ.get("S3_SECRET_KEY")
        bucket_name = os.environ.get("S3_BUCKET_NAME", "geospatial-files")
        region_name = os.environ.get("S3_REGION_NAME", "us-east-1")

        if not all((endpoint_url, access_key, secret_key)):
            raise CommandError("S3 storage credentials are not configured.")

        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
        )
        deadline = time.monotonic() + max(options["wait_seconds"], 0)

        while True:
            try:
                existing_buckets = {
                    bucket["Name"] for bucket in client.list_buckets()["Buckets"]
                }
                if bucket_name not in existing_buckets:
                    client.create_bucket(Bucket=bucket_name)
                self.stdout.write(
                    self.style.SUCCESS(f"Storage bucket ready: {bucket_name}")
                )
                return
            except (EndpointConnectionError, ConnectionClosedError) as error:
                if time.monotonic() >= deadline:
                    raise CommandError(
                        "Object storage did not become available in time."
                    ) from error
                time.sleep(1)
