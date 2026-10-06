import uuid
from pathlib import Path

from django.db import models


def geospatial_file_upload_path(instance, filename: str) -> str:
    safe_filename = Path(filename.replace("\\", "/")).name
    return f"uploads/{instance.id}/{safe_filename}"


class GeospatialFile(models.Model):
    class FileType(models.TextChoices):
        SHAPEFILE = "SHAPEFILE", "Shapefile"
        KML = "KML", "KML"

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to=geospatial_file_upload_path)
    filename = models.CharField(max_length=255)
    file_type = models.CharField(max_length=20, choices=FileType.choices)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
        db_index=True,
    )
    source_crs = models.CharField(max_length=255, null=True, blank=True)
    measurement_crs = models.CharField(max_length=255, null=True, blank=True)
    feature_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.filename} ({self.status})"


class Feature(models.Model):
    class MeasurementType(models.TextChoices):
        AREA = "AREA", "Area"
        LENGTH = "LENGTH", "Length"

    class MeasurementStatus(models.TextChoices):
        CALCULATED = "CALCULATED", "Calculated"
        NOT_REQUIRED = "NOT_REQUIRED", "Not required"
        UNSUPPORTED = "UNSUPPORTED", "Unsupported"

    geospatial_file = models.ForeignKey(
        GeospatialFile,
        on_delete=models.CASCADE,
        related_name="features",
    )
    feature_index = models.PositiveIntegerField()
    geometry_type = models.CharField(max_length=50)
    geometry = models.JSONField()
    properties = models.JSONField(default=dict)
    measurement_type = models.CharField(
        max_length=20,
        choices=MeasurementType.choices,
        null=True,
        blank=True,
    )
    measurement_value = models.FloatField(null=True, blank=True)
    measurement_status = models.CharField(
        max_length=20,
        choices=MeasurementStatus.choices,
    )

    class Meta:
        ordering = ["feature_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["geospatial_file", "feature_index"],
                name="unique_feature_index_per_file",
            )
        ]

    def __str__(self) -> str:
        return f"{self.geospatial_file_id}:{self.feature_index}"
