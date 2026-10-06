# API Design

The API provides the three endpoints required to upload a geospatial file, inspect its processing status, and retrieve paginated feature measurements.

## Endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/files/` | Upload a KML or zipped Shapefile |
| `GET` | `/api/files/{id}/` | Retrieve file information and processing status |
| `GET` | `/api/files/{id}/measurements/` | Retrieve paginated feature measurements |

No listing, deletion, authentication, or additional processing endpoints are included.

## Upload a file

```http
POST /api/files/
Content-Type: multipart/form-data
```

### Request

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `file` | File | Yes | A `.kml` file or `.zip` containing one Shapefile |

The API infers `file_type` from the uploaded file. The client does not send it separately.

```bash
curl -X POST http://localhost:8000/api/files/ \
  -F "file=@survey.kml"
```

### Successful response

```http
HTTP/1.1 202 Accepted
Location: /api/files/3f749d5a-4878-4ff6-b647-d0bdfe610563/
```

```json
{
  "id": "3f749d5a-4878-4ff6-b647-d0bdfe610563",
  "filename": "survey.kml",
  "file_type": "KML",
  "status": "QUEUED",
  "source_crs": null,
  "measurement_crs": null,
  "feature_count": 0,
  "error_message": "",
  "created_at": "2026-10-06T17:30:00Z",
  "updated_at": "2026-10-06T17:30:00Z"
}
```

The API saves the file and creates a queued `GeospatialFile` row. A worker processes it asynchronously.

### Upload errors

Unsupported extension:

```http
HTTP/1.1 400 Bad Request
```

```json
{
  "file": [
    "Only .kml and .zip files are supported."
  ]
}
```

Missing file:

```http
HTTP/1.1 400 Bad Request
```

```json
{
  "file": [
    "No file was submitted."
  ]
}
```

File too large:

```http
HTTP/1.1 413 Content Too Large
```

```json
{
  "detail": "The uploaded file exceeds the maximum allowed size."
}
```

Detailed validation, such as opening the KML or confirming Shapefile components, happens in the worker. A processing failure is recorded on the file row.

## Retrieve file information

```http
GET /api/files/{id}/
```

```bash
curl http://localhost:8000/api/files/3f749d5a-4878-4ff6-b647-d0bdfe610563/
```

### Queued response

```http
HTTP/1.1 200 OK
```

```json
{
  "id": "3f749d5a-4878-4ff6-b647-d0bdfe610563",
  "filename": "survey.kml",
  "file_type": "KML",
  "status": "QUEUED",
  "source_crs": null,
  "measurement_crs": null,
  "feature_count": 0,
  "error_message": "",
  "created_at": "2026-10-06T17:30:00Z",
  "updated_at": "2026-10-06T17:30:00Z"
}
```

A file being processed uses the same response with `status` set to `PROCESSING`.

### Completed response

```json
{
  "id": "3f749d5a-4878-4ff6-b647-d0bdfe610563",
  "filename": "survey.kml",
  "file_type": "KML",
  "status": "COMPLETED",
  "source_crs": "EPSG:4326",
  "measurement_crs": "EPSG:32643",
  "feature_count": 250,
  "error_message": "",
  "created_at": "2026-10-06T17:30:00Z",
  "updated_at": "2026-10-06T17:30:08Z"
}
```

### Failed response

The resource still exists, so the endpoint returns `200 OK` with a failed status:

```json
{
  "id": "3f749d5a-4878-4ff6-b647-d0bdfe610563",
  "filename": "parcels.zip",
  "file_type": "SHAPEFILE",
  "status": "FAILED",
  "source_crs": null,
  "measurement_crs": null,
  "feature_count": 0,
  "error_message": "The Shapefile does not contain CRS information.",
  "created_at": "2026-10-06T17:30:00Z",
  "updated_at": "2026-10-06T17:30:04Z"
}
```

File status values are:

```text
QUEUED
PROCESSING
COMPLETED
FAILED
```

### Unknown file

```http
HTTP/1.1 404 Not Found
```

```json
{
  "detail": "Not found."
}
```

## Retrieve feature measurements

```http
GET /api/files/{id}/measurements/
```

### Pagination

| Parameter | Default | Maximum | Description |
| --- | ---: | ---: | --- |
| `page` | `1` | — | Page number |
| `page_size` | `100` | `500` | Features returned per page |

```http
GET /api/files/3f749d5a-4878-4ff6-b647-d0bdfe610563/measurements/?page=1&page_size=100
```

Features are ordered by `feature_index`, beginning at index `0`.

### Completed file

```http
HTTP/1.1 200 OK
```

```json
{
  "file_id": "3f749d5a-4878-4ff6-b647-d0bdfe610563",
  "status": "COMPLETED",
  "source_crs": "EPSG:4326",
  "measurement_crs": "EPSG:32643",
  "count": 250,
  "next": "http://localhost:8000/api/files/3f749d5a-4878-4ff6-b647-d0bdfe610563/measurements/?page=2&page_size=100",
  "previous": null,
  "results": [
    {
      "feature_index": 0,
      "geometry_type": "Polygon",
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [77.5901, 12.9701],
            [77.5910, 12.9701],
            [77.5910, 12.9710],
            [77.5901, 12.9701]
          ]
        ]
      },
      "properties": {
        "name": "Parcel A",
        "owner": "Example"
      },
      "measurement": {
        "type": "AREA",
        "value": 5421.76,
        "unit": "m2",
        "status": "CALCULATED"
      }
    },
    {
      "feature_index": 1,
      "geometry_type": "LineString",
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [77.5901, 12.9701],
          [77.5950, 12.9750]
        ]
      },
      "properties": {
        "name": "Access road"
      },
      "measurement": {
        "type": "LENGTH",
        "value": 747.32,
        "unit": "m",
        "status": "CALCULATED"
      }
    },
    {
      "feature_index": 2,
      "geometry_type": "Point",
      "geometry": {
        "type": "Point",
        "coordinates": [77.5946, 12.9716]
      },
      "properties": {
        "name": "Survey marker"
      },
      "measurement": {
        "type": null,
        "value": null,
        "unit": null,
        "status": "NOT_REQUIRED"
      }
    }
  ]
}
```

Geometry coordinates remain in `source_crs`. The projected `measurement_crs` is used only to calculate measurements. Measurement values are returned without API-side rounding.

### Unsupported geometry

An unsupported geometry does not fail the entire file:

```json
{
  "feature_index": 5,
  "geometry_type": "GeometryCollection",
  "geometry": {
    "type": "GeometryCollection",
    "geometries": []
  },
  "properties": {},
  "measurement": {
    "type": null,
    "value": null,
    "unit": null,
    "status": "UNSUPPORTED"
  }
}
```

### File is not ready

For a `QUEUED` or `PROCESSING` file:

```http
HTTP/1.1 202 Accepted
Retry-After: 2
```

```json
{
  "file_id": "3f749d5a-4878-4ff6-b647-d0bdfe610563",
  "status": "PROCESSING",
  "detail": "Measurements are not available yet."
}
```

### Processing failed

```http
HTTP/1.1 409 Conflict
```

```json
{
  "file_id": "3f749d5a-4878-4ff6-b647-d0bdfe610563",
  "status": "FAILED",
  "detail": "Measurements are unavailable because file processing failed.",
  "error_message": "The Shapefile does not contain CRS information."
}
```

### Empty completed file

```json
{
  "file_id": "3f749d5a-4878-4ff6-b647-d0bdfe610563",
  "status": "COMPLETED",
  "source_crs": "EPSG:4326",
  "measurement_crs": null,
  "count": 0,
  "next": null,
  "previous": null,
  "results": []
}
```

## Response conventions

- Dates use ISO 8601 in UTC.
- Identifiers use UUIDs.
- Feature indexes start at zero.
- Area units are `m2`.
- Length units are `m`.
- Geometry and properties come from the uploaded file.
- Results become visible after the complete file has been processed successfully.
- Django REST Framework handles request validation and standard `404` responses.
