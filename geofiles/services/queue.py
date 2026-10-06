from django.db import connection, transaction

from geofiles.models import GeospatialFile


def claim_next_file() -> GeospatialFile | None:
    """Atomically claim the oldest queued file for the current worker."""
    with transaction.atomic():
        lock_options = {}
        if connection.features.has_select_for_update_skip_locked:
            lock_options["skip_locked"] = True

        geospatial_file = (
            GeospatialFile.objects.select_for_update(**lock_options)
            .filter(status=GeospatialFile.Status.QUEUED)
            .order_by("created_at")
            .first()
        )
        if geospatial_file is None:
            return None

        geospatial_file.status = GeospatialFile.Status.PROCESSING
        geospatial_file.error_message = ""
        geospatial_file.save(
            update_fields=("status", "error_message", "updated_at")
        )
        return geospatial_file
