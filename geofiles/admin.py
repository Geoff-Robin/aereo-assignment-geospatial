from django.contrib import admin

from geofiles.models import Feature, GeospatialFile


@admin.register(GeospatialFile)
class GeospatialFileAdmin(admin.ModelAdmin):
    list_display = ("id", "filename", "file_type", "status", "feature_count")
    list_filter = ("file_type", "status")
    search_fields = ("id", "filename")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "geospatial_file",
        "feature_index",
        "geometry_type",
        "measurement_status",
    )
    list_filter = ("geometry_type", "measurement_status")
    search_fields = ("geospatial_file__id", "geospatial_file__filename")
