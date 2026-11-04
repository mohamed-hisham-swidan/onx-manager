import { useSearchParams } from "react-router-dom";
import { MARKETPLACE_PAGE_SIZE } from "@/server_manager/hooks/usePlugins";
import { Icon } from "@/components/ui/Icon";
import { getPageItems, type PaginationPageItem } from "./paginationUtils";

export type { PaginationPageItem };

export interface PaginationProps {
  totalItems: number;
  pageSize?: number;
  param?: string;
  page?: number;
  onPageChange?: (page: number) => void;
  className?: string;
}

export function Pagination({
  totalItems,
  pageSize = MARKETPLACE_PAGE_SIZE,
  param = "page",
  page: controlledPage,
  onPageChange,
  className = "",
}: PaginationProps) {
  const [searchParams, setSearchParams] = useSearchParams();

  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));

  let currentPage: number;
  if (controlledPage !== undefined) {
    currentPage = Math.min(Math.max(controlledPage, 1), totalPages);
  } else {
    const rawPage = Number.parseInt(searchParams.get(param) ?? "1", 10);
    currentPage = Number.isNaN(rawPage)
      ? 1
      : Math.min(Math.max(rawPage, 1), totalPages);
  }

  if (totalPages <= 1) {
    return null;
  }

  function goTo(nextPage: number) {
    const target = Math.min(Math.max(nextPage, 1), totalPages);
    if (onPageChange) {
      onPageChange(target);
    } else {
      const newParams = new URLSearchParams(searchParams);
      newParams.set(param, String(target));
      setSearchParams(newParams);
    }
  }

  return (
    <nav
      aria-label="Pagination"
      data-testid="pagination"
      className={`flex items-center justify-center gap-1 pt-6 ${className}`}
    >
      <button
        type="button"
        aria-label="Previous page"
        disabled={currentPage === 1}
        onClick={() => goTo(currentPage - 1)}
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-text-secondary transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Icon name="chevron-left" size={16} />
      </button>

      {getPageItems(currentPage, totalPages).map((item, index) =>
        item === "ellipsis" ? (
          <span
            key={`ellipsis-${index}`}
            className="flex h-9 w-9 items-center justify-center text-sm text-text-muted"
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
                ? "bg-accent-primary text-accent-contrast-text"
                : "text-text-secondary hover:bg-surface-hover"
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
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-text-secondary transition-colors hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-40"
      >
        <Icon name="chevron-right" size={16} />
      </button>
    </nav>
  );
}
