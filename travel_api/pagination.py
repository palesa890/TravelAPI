from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardPagination(PageNumberPagination):
    """Global default (see REST_FRAMEWORK['DEFAULT_PAGINATION_CLASS'])."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class LargeResultsPagination(StandardPagination):
    """For browsing catalogues (destinations, activities, accommodations)."""
    page_size = 50
    max_page_size = 200


class ReviewPagination(PageNumberPagination):
    """Smaller pages for reviews, with extra page metadata."""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50

    def get_paginated_response(self, data):
        return Response({
            'count': self.page.paginator.count,
            'total_pages': self.page.paginator.num_pages,
            'current_page': self.page.number,
            'next': self.get_next_link(),
            'previous': self.get_previous_link(),
            'results': data,
        })

    def get_paginated_response_schema(self, schema):
        response_schema = super().get_paginated_response_schema(schema)
        response_schema['properties'].update({
            'total_pages': {'type': 'integer', 'example': 3},
            'current_page': {'type': 'integer', 'example': 1},
        })
        return response_schema


def paginated_response(request, queryset, serializer_class, view=None, context=None):
    """Paginate a queryset inside a function-based view or plain APIView."""
    paginator = StandardPagination()
    page = paginator.paginate_queryset(queryset, request, view=view)
    serializer = serializer_class(page, many=True, context=context or {'request': request})
    return paginator.get_paginated_response(serializer.data)
