from pathlib import Path

from django.conf import settings
from rest_framework import serializers

from geofiles.models import Feature, GeospatialFile


class GeospatialFileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, uploaded_file):
        filename = Path(uploaded_file.name.replace("\\", "/")).name
        suffix = Path(filename).suffix.lower()

        if suffix not in {".kml", ".zip"}:
            raise serializers.ValidationError(
                "Only .kml and .zip files are supported."
            )
        if uploaded_file.size > settings.MAX_UPLOAD_SIZE:
            raise serializers.ValidationError(
                "The uploaded file exceeds the maximum allowed size.",
                code="file_too_large",
            )

        uploaded_file.original_filename = filename
        uploaded_file.geospatial_file_type = (
            GeospatialFile.FileType.KML
            if suffix == ".kml"
            else GeospatialFile.FileType.SHAPEFILE
        )
        return uploaded_file

    def create(self, validated_data):
        uploaded_file = validated_data["file"]
        return GeospatialFile.objects.create(
            file=uploaded_file,
            filename=uploaded_file.original_filename,
            file_type=uploaded_file.geospatial_file_type,
        )


class GeospatialFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeospatialFile
        fields = (
            "id",
            "filename",
            "file_type",
            "status",
            "source_crs",
            "measurement_crs",
            "feature_count",
            "error_message",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class FeatureMeasurementSerializer(serializers.ModelSerializer):
    measurement = serializers.SerializerMethodField()

    class Meta:
        model = Feature
        fields = (
            "feature_index",
            "geometry_type",
            "geometry",
            "properties",
            "measurement",
        )

    def get_measurement(self, feature):
        unit = None
        if feature.measurement_type == Feature.MeasurementType.AREA:
            unit = "m2"
        elif feature.measurement_type == Feature.MeasurementType.LENGTH:
            unit = "m"

        return {
            "type": feature.measurement_type,
            "value": feature.measurement_value,
            "unit": unit,
            "status": feature.measurement_status,
        }
