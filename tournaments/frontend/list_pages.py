"""Shared five-item paging contract for read-only lists."""
PAGE_SIZE = 5


def page_bounds(params):
    try:
        limit = int(params.get('limit', PAGE_SIZE))
        offset = int(params.get('offset', 0))
    except (TypeError, ValueError) as error:
        raise ValueError('Invalid pagination') from error
    if limit != PAGE_SIZE or offset < 0:
        raise ValueError('limit must be 5 and offset must be nonnegative')
    return offset, limit


def page_payload(results, count, offset, limit=PAGE_SIZE, **metadata):
    return {
        'results': results, 'count': count,
        'next_offset': offset + limit if offset + limit < count else None,
        **metadata,
    }


def queryset_page(queryset, serialize, offset=0, limit=PAGE_SIZE):
    count = queryset.count()
    return page_payload([serialize(item) for item in queryset[offset:offset + limit]], count, offset, limit)
