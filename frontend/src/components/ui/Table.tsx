import React from "react";
import { Icon } from "@/components/ui/Icon";

export interface Column<T> {
  key: string;
  header: React.ReactNode;
  sortable?: boolean;
  width?: string;
  align?: "left" | "center" | "right";
  render?: (row: T, index: number) => React.ReactNode;
}

export interface TableProps<T> {
  data: T[];
  columns: Column<T>[];
  keyField: keyof T | ((row: T) => string);
  sortColumn?: string;
  sortDirection?: "asc" | "desc";
  onSort?: (key: string) => void;
  emptyMessage?: React.ReactNode;
  loading?: boolean;
  density?: "compact" | "comfortable";
  onRowClick?: (row: T) => void;
  className?: string;
}

export function Table<T>({
  data,
  columns,
  keyField,
  sortColumn,
  sortDirection = "asc",
  onSort,
  emptyMessage = "No data found",
  loading = false,
  density = "comfortable",
  onRowClick,
  className = "",
}: TableProps<T>) {
  const getRowKey = (row: T, index: number): string => {
    if (typeof keyField === "function") return keyField(row);
    return String(row[keyField] ?? index);
  };

  const paddingClasses =
    density === "compact"
      ? "px-3 py-1.5 text-xs"
      : "px-4 py-3 text-sm";

  return (
    <div className={`w-full overflow-x-auto rounded-xl border border-border-subtle bg-surface-card shadow-xs ${className}`}>
      <table className="w-full border-collapse text-left text-text-primary">
        <thead>
          <tr className="border-b border-border-subtle bg-surface-muted/40 text-xs font-semibold uppercase tracking-wider text-text-secondary">
            {columns.map((col) => {
              const isSorted = sortColumn === col.key;
              const alignClass =
                col.align === "right"
                  ? "text-right"
                  : col.align === "center"
                  ? "text-center"
                  : "text-left";

              return (
                <th
                  key={col.key}
                  style={col.width ? { width: col.width } : undefined}
                  className={`px-4 py-2.5 ${alignClass} ${
                    col.sortable ? "cursor-pointer select-none hover:text-text-primary" : ""
                  }`}
                  onClick={() => col.sortable && onSort?.(col.key)}
                >
                  <div
                    className={`inline-flex items-center gap-1.5 ${
                      col.align === "right"
                        ? "justify-end"
                        : col.align === "center"
                        ? "justify-center"
                        : "justify-start"
                    }`}
                  >
                    <span>{col.header}</span>
                    {col.sortable && (
                      <span className="text-text-muted">
                        {isSorted ? (
                          sortDirection === "asc" ? (
                            <Icon name="chevron-up" size={14} className="text-accent-primary" />
                          ) : (
                            <Icon name="chevron-down" size={14} className="text-accent-primary" />
                          )
                        ) : (
                          <span className="opacity-0 group-hover:opacity-100">
                            <Icon name="chevron-down" size={14} />
                          </span>
                        )}
                      </span>
                    )}
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-border-subtle">
          {loading ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-text-muted">
                <div className="inline-flex items-center gap-2">
                  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-accent-primary border-t-transparent" />
                  <span>Loading data...</span>
                </div>
              </td>
            </tr>
          ) : data.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="px-4 py-8 text-center text-text-muted">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            data.map((row, rowIdx) => {
              const rowKey = getRowKey(row, rowIdx);
              const isClickable = !!onRowClick;

              return (
                <tr
                  key={rowKey}
                  onClick={() => onRowClick?.(row)}
                  tabIndex={isClickable ? 0 : undefined}
                  className={`transition-colors ${
                    isClickable
                      ? "cursor-pointer hover:bg-surface-hover focus:bg-surface-hover focus:outline-hidden"
                      : "hover:bg-surface-hover/50"
                  }`}
                >
                  {columns.map((col) => {
                    const alignClass =
                      col.align === "right"
                        ? "text-right"
                        : col.align === "center"
                        ? "text-center"
                        : "text-left";

                    return (
                      <td key={col.key} className={`${paddingClasses} ${alignClass}`}>
                        {col.render
                          ? col.render(row, rowIdx)
                          : (row as Record<string, unknown>)[col.key] !== undefined
                          ? String((row as Record<string, unknown>)[col.key])
                          : null}
                      </td>
                    );
                  })}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
