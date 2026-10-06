from __future__ import annotations

import math
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pyproj import CRS
from shapely.geometry import mapping

from geofiles.models import Feature, GeospatialFile


class ProcessingError(Exception):
    """Raised when an uploaded file cannot be processed safely."""


@dataclass(frozen=True)
class ProcessedFeature:
    feature_index: int
    geometry_type: str
    geometry: dict[str, Any]
    properties: dict[str, Any]
    measurement_type: str | None
    measurement_value: float | None
    measurement_status: str


@dataclass(frozen=True)
class ProcessedDataset:
    source_crs: str
    measurement_crs: str | None
    features: list[ProcessedFeature]


def process_geospatial_file(geospatial_file: GeospatialFile) -> None:
    dataset = load_and_measure(
        Path(geospatial_file.file.path), geospatial_file.file_type
    )

    feature_rows = [
        Feature(
            geospatial_file_id=geospatial_file.id,
            feature_index=feature.feature_index,
            geometry_type=feature.geometry_type,
            geometry=feature.geometry,
            properties=feature.properties,
            measurement_type=feature.measurement_type,
            measurement_value=feature.measurement_value,
            measurement_status=feature.measurement_status,
        )
        for feature in dataset.features
    ]

    with transaction.atomic():
        locked_file = GeospatialFile.objects.select_for_update().get(
            pk=geospatial_file.pk
        )
        locked_file.features.all().delete()
        Feature.objects.bulk_create(feature_rows, batch_size=1000)

        locked_file.source_crs = dataset.source_crs
        locked_file.measurement_crs = dataset.measurement_crs
        locked_file.feature_count = len(feature_rows)
        locked_file.status = GeospatialFile.Status.COMPLETED
        locked_file.error_message = ""
        locked_file.save(
            update_fields=(
                "source_crs",
                "measurement_crs",
                "feature_count",
                "status",
                "error_message",
                "updated_at",
            )
        )


def mark_file_failed(geospatial_file: GeospatialFile, error: Exception) -> None:
    GeospatialFile.objects.filter(pk=geospatial_file.pk).update(
        status=GeospatialFile.Status.FAILED,
        error_message=str(error)[:4000],
        updated_at=timezone.now(),
    )


def load_and_measure(file_path: Path, file_type: str) -> ProcessedDataset:
    if file_type == GeospatialFile.FileType.SHAPEFILE:
        gdf = _read_zipped_shapefile(file_path)
    elif file_type == GeospatialFile.FileType.KML:
        gdf = _read_kml(file_path)
    else:
        raise ProcessingError(f"Unsupported file type: {file_type}")

    return measure_geodataframe(gdf)


def measure_geodataframe(gdf: gpd.GeoDataFrame) -> ProcessedDataset:
    if gdf.crs is None:
        raise ProcessingError("The geospatial file does not contain CRS information.")

    source_crs = _format_crs(gdf.crs)
    geometry_types = gdf.geometry.geom_type
    measurable_mask = geometry_types.isin(
        ["Polygon", "MultiPolygon", "LineString", "MultiLineString"]
    ) & gdf.geometry.notna()
    measurable = gdf.loc[measurable_mask & ~gdf.geometry.is_empty]

    measurement_crs = None
    projected = None
    if not measurable.empty:
        selected_crs = _select_measurement_crs(measurable)
        measurement_crs = _format_crs(selected_crs)
        projected = gdf.to_crs(selected_crs)

    processed_features = []
    geometry_column = gdf.geometry.name
    property_columns = [
        column for column in gdf.columns if column != geometry_column
    ]

    for position, (_, row) in enumerate(gdf.iterrows()):
        geometry = row[geometry_column]
        geometry_type = (
            geometry.geom_type if geometry is not None else "Unknown"
        )
        properties = {
            str(column): _to_json_value(row[column])
            for column in property_columns
        }
        geometry_json = (
            _to_json_value(mapping(geometry)) if geometry is not None else {}
        )

        measurement_type = None
        measurement_value = None
        measurement_status = Feature.MeasurementStatus.UNSUPPORTED

        if geometry_type in {"Point", "MultiPoint"}:
            measurement_status = Feature.MeasurementStatus.NOT_REQUIRED
        elif geometry_type in {"Polygon", "MultiPolygon"}:
            measurement_type = Feature.MeasurementType.AREA
            if projected is not None and not geometry.is_empty:
                measurement_value = _finite_float(
                    projected.geometry.iloc[position].area
                )
            if measurement_value is not None:
                measurement_status = Feature.MeasurementStatus.CALCULATED
        elif geometry_type in {"LineString", "MultiLineString"}:
            measurement_type = Feature.MeasurementType.LENGTH
            if projected is not None and not geometry.is_empty:
                measurement_value = _finite_float(
                    projected.geometry.iloc[position].length
                )
            if measurement_value is not None:
                measurement_status = Feature.MeasurementStatus.CALCULATED

        processed_features.append(
            ProcessedFeature(
                feature_index=position,
                geometry_type=geometry_type,
                geometry=geometry_json,
                properties=properties,
                measurement_type=measurement_type,
                measurement_value=measurement_value,
                measurement_status=measurement_status,
            )
        )

    return ProcessedDataset(
        source_crs=source_crs,
        measurement_crs=measurement_crs,
        features=processed_features,
    )


def _read_zipped_shapefile(file_path: Path) -> gpd.GeoDataFrame:
    try:
        archive = zipfile.ZipFile(file_path)
    except zipfile.BadZipFile as error:
        raise ProcessingError("The uploaded ZIP file is invalid.") from error

    with archive, tempfile.TemporaryDirectory() as temporary_directory:
        extraction_root = Path(temporary_directory).resolve()
        members = [member for member in archive.infolist() if not member.is_dir()]
        total_size = sum(member.file_size for member in members)
        if total_size > settings.MAX_ARCHIVE_UNCOMPRESSED_SIZE:
            raise ProcessingError(
                "The uncompressed Shapefile archive exceeds the allowed size."
            )

        for member in members:
            relative_path = PurePosixPath(member.filename.replace("\\", "/"))
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ProcessingError("The ZIP file contains an unsafe path.")

            target = extraction_root.joinpath(*relative_path.parts).resolve()
            if extraction_root not in target.parents:
                raise ProcessingError("The ZIP file contains an unsafe path.")

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)

        shapefiles = [
            path
            for path in extraction_root.rglob("*")
            if path.is_file() and path.suffix.lower() == ".shp"
        ]
        if len(shapefiles) != 1:
            raise ProcessingError(
                "The ZIP file must contain exactly one Shapefile dataset."
            )

        shapefile = shapefiles[0]
        sibling_suffixes = {
            path.suffix.lower()
            for path in shapefile.parent.iterdir()
            if path.is_file() and path.stem.lower() == shapefile.stem.lower()
        }
        missing = {".shx", ".dbf"} - sibling_suffixes
        if missing:
            missing_names = ", ".join(sorted(missing))
            raise ProcessingError(
                f"The Shapefile is missing required component(s): {missing_names}."
            )

        try:
            return gpd.read_file(shapefile, engine="pyogrio")
        except Exception as error:
            raise ProcessingError("The Shapefile dataset is invalid.") from error


def _read_kml(file_path: Path) -> gpd.GeoDataFrame:
    try:
        layers = pyogrio.list_layers(file_path)
    except Exception as error:
        raise ProcessingError("The uploaded KML file is invalid.") from error

    if len(layers) == 0:
        raise ProcessingError("The KML file does not contain any layers.")

    frames = []
    for layer in layers:
        try:
            frame = gpd.read_file(file_path, layer=layer[0], engine="pyogrio")
        except Exception as error:
            raise ProcessingError("The uploaded KML file is invalid.") from error
        if frame.crs is None:
            frame = frame.set_crs("EPSG:4326")
        else:
            frame = frame.to_crs("EPSG:4326")
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    return gpd.GeoDataFrame(combined, geometry="geometry", crs="EPSG:4326")


def _select_measurement_crs(gdf: gpd.GeoDataFrame) -> CRS:
    source_crs = CRS.from_user_input(gdf.crs)
    if source_crs.is_projected and _uses_metres(source_crs):
        return source_crs

    try:
        estimated = gdf.estimate_utm_crs()
    except Exception as error:
        raise ProcessingError(
            "An appropriate projected CRS could not be determined."
        ) from error
    if estimated is None:
        raise ProcessingError(
            "An appropriate projected CRS could not be determined."
        )
    return CRS.from_user_input(estimated)


def _uses_metres(crs: CRS) -> bool:
    return bool(crs.axis_info) and all(
        math.isclose(axis.unit_conversion_factor or 0, 1.0)
        for axis in crs.axis_info[:2]
    )


def _format_crs(crs_value) -> str:
    crs = CRS.from_user_input(crs_value)
    authority = crs.to_authority()
    if authority:
        return f"{authority[0]}:{authority[1]}"
    return crs.to_string()


def _finite_float(value) -> float | None:
    result = float(value)
    return result if math.isfinite(result) else None


def _to_json_value(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_value(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None

    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if hasattr(value, "item"):
        try:
            return _to_json_value(value.item())
        except (TypeError, ValueError):
            pass

    if isinstance(value, (str, int, bool)):
        return value
    return str(value)
