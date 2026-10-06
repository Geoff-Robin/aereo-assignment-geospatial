# Geospatial File Measurement API

A Django REST API that accepts KML files and zipped Shapefiles, processes them asynchronously, and returns paginated area and length measurements for their features.

## Stack

- Django and Django REST Framework
- PostgreSQL
- MinIO object storage
- GeoPandas with Pyogrio
- Shapely and PyProj
- Docker Compose

## Run with Docker

Docker Compose starts PostgreSQL, MinIO, applies migrations, runs one API service, and creates the worker service. Scale the worker service to the required three workers:

```bash
docker compose up --build -d --scale worker=3
```

The API is available at `http://localhost:8000`.
The MinIO console is available at `http://localhost:9001`.

The MinIO image is built locally from the pinned official source tag in `Dockerfile.minio`; application credentials are not passed to a third-party prebuilt MinIO image.

Environment variables have development defaults in `compose.yaml`. To override them, copy `.env.example` to `.env` and update the values before starting the services.

```bash
cp .env.example .env
```

Stop the services with:

```bash
docker compose down
```

To also remove the PostgreSQL and MinIO data volumes:

```bash
docker compose down --volumes
```

## Local development

Install the locked dependencies:

```bash
uv sync
```

Without PostgreSQL and S3 environment variables, Django uses SQLite and local filesystem storage for lightweight local development and tests. The concurrent worker queue and MinIO storage are configured through Docker Compose.

Run the tests:

```bash
uv run python manage.py test
```

## API

### Upload

```http
POST /api/files/
Content-Type: multipart/form-data
```

```bash
curl -X POST http://localhost:8000/api/files/ \
  -F "file=@survey.kml"
```

The upload field is named `file`. It accepts:

- A `.kml` file
- A `.zip` containing exactly one Shapefile dataset

The endpoint returns `202 Accepted` with a UUID and `QUEUED` status.

### File information

```http
GET /api/files/{id}/
```

The response includes the filename, source CRS, measurement CRS, feature count, and one of these statuses:

```text
QUEUED
PROCESSING
COMPLETED
FAILED
```

### Measurements

```http
GET /api/files/{id}/measurements/?page=1&page_size=100
```

Results are ordered by feature index and paginated. The default page size is 100 and the maximum is 500.

- Polygon and MultiPolygon features return area in `m2`.
- LineString and MultiLineString features return length in `m`.
- Point and MultiPoint features use `NOT_REQUIRED`.
- Other geometry types use `UNSUPPORTED` without failing the file.

The complete request and response contract is documented in [docs/api-design.md](docs/api-design.md). The agreed database structure is documented in [docs/data-models.md](docs/data-models.md).

## Architecture

The API and workers use the same Django application image. PostgreSQL stores file metadata, object keys, queue state, extracted features, and measurements. MinIO stores uploaded files and exposes the same object key to the API and every worker.

Processing flow:

1. The API validates the extension, uploads the file to MinIO under `uploads/<file-uuid>/<filename>`, and creates a `QUEUED` `GeospatialFile` row.
2. Each worker atomically claims the oldest queued row using `select_for_update(skip_locked=True)` and changes it to `PROCESSING`.
3. The worker downloads the object into a temporary local file, then Pyogrio loads the KML or extracted Shapefile into a GeoPandas GeoDataFrame.
4. Geographic coordinates are transformed to an estimated UTM CRS before measurement.
5. Shapely-backed vector operations calculate polygon area and line length.
6. The worker stores GeoJSON geometry, properties, and measurements, then changes the file to `COMPLETED`.
7. Processing errors change the file to `FAILED` and expose a safe error message through the status endpoint.

## CRS handling

KML data is normalized to EPSG:4326. Shapefile CRS information is read from its projection metadata. Files without a known CRS fail because measurements cannot safely be calculated.

If the source CRS is projected in metres, it is used for measurement. Otherwise, GeoPandas selects an appropriate UTM CRS from the dataset bounds. Source geometry remains unchanged in the API response; the projected copy is used only for area and length calculations.

## Design decisions

- `GeospatialFile` doubles as the queue entry because each upload has exactly one processing task. A separate jobs table would duplicate its state.
- PostgreSQL row locking allows three workers to claim independent files without Redis or another queue service.
- Django's S3 storage backend gives the API and workers a shared MinIO object key without a shared filesystem mount. UUID-based keys prevent filename collisions.
- Geometry is stored as JSON rather than PostGIS because the required queries are by file ID, not by spatial relationship.
- GeoPandas and Pyogrio keep file ingestion and vectorized processing concise. Uploaded and uncompressed archive sizes are limited because each worker loads a dataset into memory.
- Shapefile ZIP extraction rejects unsafe paths and requires `.shp`, `.shx`, and `.dbf` components.

## Learning

This implementation demonstrates that reliable geospatial measurement requires separating source geometry from measurement geometry. Latitude and longitude coordinates are preserved for the response while a projected copy is used for measurements in metres. It also demonstrates a small PostgreSQL-backed work queue using Django's transaction and locking primitives.

## Future scope

- Add retry leases for jobs interrupted by worker or host failures.
- Stream or chunk very large datasets instead of loading an entire layer into memory.
