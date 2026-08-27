import { useSearchParams } from "react-router-dom";
import { MARKETPLACE_PAGE_SIZE } from "@/server_manager/hooks/usePlugins";
import { Icon } from "@/components/ui/Icon";
import { getPageItems, type PaginationPageItem } from "./paginationUtils";

export type { PaginationPageItem };

interface PaginationProps {
  totalItems: number;
  pageSize?: number;
  param?: string;
}

export function Pagination({
  totalItems,
  pageSize = MARKETPLACE_PAGE_SIZE,
  param = "page",
}: PaginationProps) {
  const [searchParams, setSearchParams] = useSearchParams();

  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const rawPage = Number.parseInt(searchParams.get(param) ?? "1", 10);
  const currentPage = Number.isNaN(rawPage)
    ? 1
    : Math.min(Math.max(rawPage, 1), totalPages);

  if (totalPages <= 1) {
    return null;
  }

  function goTo(page: number) {
    const next = Math.min(Math.max(page, 1), totalPages);
    const newParams = new URLSearchParams(searchParams);
    newParams.set(param, String(next));
    setSearchParams(newParams);
  }

  return (
    <nav
      aria-label="Pagination"
      data-testid="pagination"
      className="flex items-center justify-center gap-1 pt-6"
    >
      <button
        type="button"
        aria-label="Previous page"
        disabled={currentPage === 1}
        onClick={() => goTo(currentPage - 1)}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-gray-600 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-gray-400 dark:hover:bg-gray-700/60"
      >
        <Icon name="chevron-left" size={16} />
      </button>
      {getPageItems(currentPage, totalPages).map((item, index) =>
        item === "ellipsis" ? (
          <span
            key={`ellipsis-${index}`}
            className="flex h-9 w-9 items-center justify-center text-sm text-gray-400 dark:text-gray-500"
          >
            ...
          </span>
        ) : (
          <button
            key={item}
            type="button"
            aria-label={`Page ${item}`}
            aria-current={item === currentPage ? "page" : undefined}
            onClick={() => goTo(item)}
            className={`h-9 min-w-9 rounded-lg px-2 text-sm font-medium transition-colors ${
              item === currentPage
                ? "bg-blue-600 text-white"
                : "text-gray-600 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-700/60"
            }`}
          >
            {item}
          </button>
        ),
      )}
      <button
        type="button"
        aria-label="Next page"
        disabled={currentPage === totalPages}
        onClick={() => goTo(currentPage + 1)}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-gray-600 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-gray-400 dark:hover:bg-gray-700/60"
      >
        <Icon name="chevron-right" size={16} />
      </button>
    </nav>
  );
}