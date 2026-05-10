"""Pagination helpers for the UI list pages.

Single source of truth for page size + Page math so the templates can
trust the Page object and stop computing has_prev/has_next inline.

Service-layer functions accept page/page_size as optional keyword args.
None means "don't paginate, return all rows" so MCP tools and JSON
routes that want everything stay unaffected.
"""

from dataclasses import dataclass, field

DEFAULT_PAGE_SIZE = 50


@dataclass(slots=True)
class Page[T]:
    items: list[T] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page * self.page_size < self.total

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 1
        # Ceil-divide; minimum 1 so an empty page still reads "page 1 of 1".
        return max(1, (self.total + self.page_size - 1) // self.page_size)

    @property
    def first_index(self) -> int:
        """1-indexed display number of the first item on this page."""
        if not self.items:
            return 0
        return (self.page - 1) * self.page_size + 1

    @property
    def last_index(self) -> int:
        """1-indexed display number of the last item on this page."""
        return self.first_index + len(self.items) - 1


def normalize_page(page: int | None, total: int, page_size: int = DEFAULT_PAGE_SIZE) -> int:
    """Clamp a user-supplied ?page= into [1, total_pages].

    Out-of-range pages render as empty rather than 404 so prev/next chips
    keep working when the user lands on a stale URL.
    """
    if page is None or page < 1:
        return 1
    if total == 0:
        return 1
    max_page = max(1, (total + page_size - 1) // page_size)
    return min(page, max_page)
