from django.urls import path

from geofiles.views import (
    FileMeasurementsView,
    GeospatialFileDetailView,
    GeospatialFileUploadView,
)


urlpatterns = [
    path("files/", GeospatialFileUploadView.as_view(), name="file-upload"),
    path(
        "files/<uuid:pk>/",
        GeospatialFileDetailView.as_view(),
        name="file-detail",
    ),
    path(
        "files/<uuid:pk>/measurements/",
        FileMeasurementsView.as_view(),
        name="file-measurements",
    ),
]
