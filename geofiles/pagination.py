from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class FeaturePagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 500

    def get_paginated_response(self, data, geospatial_file):
        return Response(
            {
                "file_id": str(geospatial_file.id),
                "status": geospatial_file.status,
                "source_crs": geospatial_file.source_crs,
                "measurement_crs": geospatial_file.measurement_crs,
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )
