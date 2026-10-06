from django.conf import settings
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from geofiles.models import GeospatialFile
from geofiles.pagination import FeaturePagination
from geofiles.serializers import (
    FeatureMeasurementSerializer,
    GeospatialFileSerializer,
    GeospatialFileUploadSerializer,
)


class GeospatialFileUploadView(APIView):
    def post(self, request):
        uploaded_file = request.FILES.get("file")
        if uploaded_file and uploaded_file.size > settings.MAX_UPLOAD_SIZE:
            return Response(
                {
                    "detail": (
                        "The uploaded file exceeds the maximum allowed size."
                    )
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        serializer = GeospatialFileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        geospatial_file = serializer.save()

        return Response(
            GeospatialFileSerializer(geospatial_file).data,
            status=status.HTTP_202_ACCEPTED,
            headers={
                "Location": reverse(
                    "file-detail", kwargs={"pk": geospatial_file.pk}
                )
            },
        )


class GeospatialFileDetailView(APIView):
    def get(self, request, pk):
        geospatial_file = get_object_or_404(GeospatialFile, pk=pk)
        return Response(GeospatialFileSerializer(geospatial_file).data)


class FileMeasurementsView(APIView):
    pagination_class = FeaturePagination

    def get(self, request, pk):
        geospatial_file = get_object_or_404(GeospatialFile, pk=pk)

        if geospatial_file.status in {
            GeospatialFile.Status.QUEUED,
            GeospatialFile.Status.PROCESSING,
        }:
            return Response(
                {
                    "file_id": str(geospatial_file.id),
                    "status": geospatial_file.status,
                    "detail": "Measurements are not available yet.",
                },
                status=status.HTTP_202_ACCEPTED,
                headers={"Retry-After": "2"},
            )

        if geospatial_file.status == GeospatialFile.Status.FAILED:
            return Response(
                {
                    "file_id": str(geospatial_file.id),
                    "status": geospatial_file.status,
                    "detail": (
                        "Measurements are unavailable because file processing "
                        "failed."
                    ),
                    "error_message": geospatial_file.error_message,
                },
                status=status.HTTP_409_CONFLICT,
            )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(
            geospatial_file.features.all(), request, view=self
        )
        serialized = FeatureMeasurementSerializer(page, many=True)
        return paginator.get_paginated_response(serialized.data, geospatial_file)
