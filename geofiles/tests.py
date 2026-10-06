import shutil
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import PropertyMock, patch

import geopandas as gpd
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from shapely.geometry import LineString, Point, Polygon

from geofiles.models import Feature, GeospatialFile
from geofiles.services.processor import (
    load_and_measure,
    measure_geodataframe,
    process_geospatial_file,
)
from geofiles.services.queue import claim_next_file


class FileApiTests(TestCase):
    def setUp(self):
        self.media_directory = tempfile.mkdtemp()
        self.settings_override = override_settings(
            MEDIA_ROOT=self.media_directory,
            MAX_UPLOAD_SIZE=1024,
        )
        self.settings_override.enable()
        self.client = APIClient()

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_directory)

    def test_upload_creates_queued_file(self):
        response = self.client.post(
            reverse("file-upload"),
            {"file": SimpleUploadedFile("survey.kml", b"<kml />")},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        geospatial_file = GeospatialFile.objects.get()
        self.assertEqual(geospatial_file.filename, "survey.kml")
        self.assertEqual(geospatial_file.file_type, GeospatialFile.FileType.KML)
        self.assertEqual(geospatial_file.status, GeospatialFile.Status.QUEUED)
        self.assertEqual(
            geospatial_file.file.name,
            f"uploads/{geospatial_file.id}/survey.kml",
        )
        self.assertEqual(
            response.headers["Location"],
            reverse("file-detail", kwargs={"pk": geospatial_file.pk}),
        )

    def test_upload_rejects_unsupported_extension(self):
        response = self.client.post(
            reverse("file-upload"),
            {"file": SimpleUploadedFile("survey.geojson", b"{}")},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(GeospatialFile.objects.count(), 0)

    def test_uploads_with_the_same_filename_use_different_object_keys(self):
        for _ in range(2):
            response = self.client.post(
                reverse("file-upload"),
                {"file": SimpleUploadedFile("survey.kml", b"<kml />")},
                format="multipart",
            )
            self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        stored_names = list(
            GeospatialFile.objects.order_by("created_at").values_list(
                "file", flat=True
            )
        )
        self.assertEqual(len(set(stored_names)), 2)
        self.assertTrue(all(name.endswith("/survey.kml") for name in stored_names))

    def test_upload_rejects_large_file(self):
        response = self.client.post(
            reverse("file-upload"),
            {"file": SimpleUploadedFile("survey.kml", b"x" * 1025)},
            format="multipart",
        )

        self.assertEqual(
            response.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        )
        self.assertEqual(GeospatialFile.objects.count(), 0)

    def test_file_detail_returns_processing_metadata(self):
        geospatial_file = self.create_file(status=GeospatialFile.Status.PROCESSING)

        response = self.client.get(
            reverse("file-detail", kwargs={"pk": geospatial_file.pk})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], GeospatialFile.Status.PROCESSING)

    def test_measurements_return_accepted_until_file_is_complete(self):
        geospatial_file = self.create_file(status=GeospatialFile.Status.QUEUED)

        response = self.client.get(
            reverse("file-measurements", kwargs={"pk": geospatial_file.pk})
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.headers["Retry-After"], "2")

    def test_measurements_return_failure_for_failed_file(self):
        geospatial_file = self.create_file(status=GeospatialFile.Status.FAILED)
        geospatial_file.error_message = "Invalid KML."
        geospatial_file.save(update_fields=("error_message", "updated_at"))

        response = self.client.get(
            reverse("file-measurements", kwargs={"pk": geospatial_file.pk})
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["error_message"], "Invalid KML.")

    def test_measurements_are_paginated_in_feature_order(self):
        geospatial_file = self.create_file(status=GeospatialFile.Status.COMPLETED)
        geospatial_file.source_crs = "EPSG:4326"
        geospatial_file.measurement_crs = "EPSG:32643"
        geospatial_file.feature_count = 3
        geospatial_file.save()
        Feature.objects.bulk_create(
            [
                Feature(
                    geospatial_file=geospatial_file,
                    feature_index=index,
                    geometry_type="Point",
                    geometry={"type": "Point", "coordinates": [index, index]},
                    properties={"name": f"Feature {index}"},
                    measurement_status=Feature.MeasurementStatus.NOT_REQUIRED,
                )
                for index in range(3)
            ]
        )

        response = self.client.get(
            reverse("file-measurements", kwargs={"pk": geospatial_file.pk}),
            {"page_size": 2},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(response.data["results"][0]["feature_index"], 0)
        self.assertIsNotNone(response.data["next"])

    def create_file(self, status):
        return GeospatialFile.objects.create(
            file=SimpleUploadedFile("survey.kml", b"<kml />"),
            filename="survey.kml",
            file_type=GeospatialFile.FileType.KML,
            status=status,
        )


class QueueTests(TestCase):
    def test_claim_next_file_claims_oldest_queued_file(self):
        queued = GeospatialFile.objects.create(
            file="uploads/queued.kml",
            filename="queued.kml",
            file_type=GeospatialFile.FileType.KML,
        )
        GeospatialFile.objects.create(
            file="uploads/completed.kml",
            filename="completed.kml",
            file_type=GeospatialFile.FileType.KML,
            status=GeospatialFile.Status.COMPLETED,
        )

        claimed = claim_next_file()

        self.assertEqual(claimed.pk, queued.pk)
        queued.refresh_from_db()
        self.assertEqual(queued.status, GeospatialFile.Status.PROCESSING)


class WorkerProcessingTests(TestCase):
    def setUp(self):
        self.media_directory = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_directory)
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        shutil.rmtree(self.media_directory)

    def test_worker_processing_persists_features_and_completes_file(self):
        kml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Placemark>
            <name>Marker</name>
            <Point><coordinates>77.5946,12.9716</coordinates></Point>
          </Placemark>
        </kml>
        """
        geospatial_file = GeospatialFile.objects.create(
            file=SimpleUploadedFile("survey.kml", kml),
            filename="survey.kml",
            file_type=GeospatialFile.FileType.KML,
            status=GeospatialFile.Status.PROCESSING,
        )

        with patch(
            "django.db.models.fields.files.FieldFile.path",
            new_callable=PropertyMock,
            side_effect=NotImplementedError,
        ):
            process_geospatial_file(geospatial_file)

        geospatial_file.refresh_from_db()
        self.assertEqual(geospatial_file.status, GeospatialFile.Status.COMPLETED)
        self.assertEqual(geospatial_file.source_crs, "EPSG:4326")
        self.assertEqual(geospatial_file.feature_count, 1)
        self.assertEqual(geospatial_file.features.count(), 1)


class MeasurementTests(TestCase):
    def test_measure_geodataframe_calculates_supported_geometries(self):
        gdf = gpd.GeoDataFrame(
            {"name": ["Parcel", "Road", "Marker"]},
            geometry=[
                Polygon([(77.59, 12.97), (77.60, 12.97), (77.60, 12.98)]),
                LineString([(77.59, 12.97), (77.60, 12.98)]),
                Point(77.5946, 12.9716),
            ],
            crs="EPSG:4326",
        )

        result = measure_geodataframe(gdf)

        self.assertEqual(result.source_crs, "EPSG:4326")
        self.assertEqual(result.measurement_crs, "EPSG:32643")
        self.assertEqual(
            result.features[0].measurement_type, Feature.MeasurementType.AREA
        )
        self.assertGreater(result.features[0].measurement_value, 0)
        self.assertEqual(
            result.features[1].measurement_type, Feature.MeasurementType.LENGTH
        )
        self.assertGreater(result.features[1].measurement_value, 0)
        self.assertEqual(
            result.features[2].measurement_status,
            Feature.MeasurementStatus.NOT_REQUIRED,
        )

    def test_load_and_measure_reads_kml_features(self):
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Placemark>
              <name>Marker</name>
              <Point><coordinates>77.5946,12.9716</coordinates></Point>
            </Placemark>
            <Placemark>
              <name>Route</name>
              <LineString>
                <coordinates>77.59,12.97 77.60,12.98</coordinates>
              </LineString>
            </Placemark>
          </Document>
        </kml>
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "survey.kml"
            path.write_text(kml, encoding="utf-8")

            result = load_and_measure(path, GeospatialFile.FileType.KML)

        self.assertEqual(result.source_crs, "EPSG:4326")
        self.assertEqual(len(result.features), 2)
        self.assertEqual(result.features[0].geometry_type, "Point")
        self.assertIsNone(result.features[0].properties["timestamp"])
        self.assertEqual(result.features[1].geometry_type, "LineString")

    def test_load_and_measure_reads_zipped_shapefile(self):
        gdf = gpd.GeoDataFrame(
            {"name": ["Parcel"]},
            geometry=[
                Polygon([(77.59, 12.97), (77.60, 12.97), (77.60, 12.98)])
            ],
            crs="EPSG:4326",
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shapefile = root / "parcel.shp"
            archive = root / "parcel.zip"
            gdf.to_file(shapefile, engine="pyogrio")
            with zipfile.ZipFile(archive, "w") as zipped:
                for component in root.glob("parcel.*"):
                    if component != archive:
                        zipped.write(component, component.name)

            result = load_and_measure(
                archive, GeospatialFile.FileType.SHAPEFILE
            )

        self.assertEqual(result.source_crs, "EPSG:4326")
        self.assertEqual(len(result.features), 1)
        self.assertEqual(
            result.features[0].measurement_type, Feature.MeasurementType.AREA
        )
