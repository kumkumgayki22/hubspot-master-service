import math
from typing import Dict, Any


def build_pagination_info(page: int, page_size: int, total: int) -> Dict[str, Any]:
    """
    Standard pagination envelope metadata generator.
    """
    page = max(1, page)
    page_size = max(1, page_size)
    total_pages = math.ceil(total / page_size) if total > 0 else 1

    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }
