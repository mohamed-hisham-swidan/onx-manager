import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Table, type Column } from "./Table";

interface Item {
  id: string;
  name: string;
  count: number;
}

describe("Table Primitive", () => {
  const columns: Column<Item>[] = [
    { key: "name", header: "Name", sortable: true },
    { key: "count", header: "Count", align: "right" },
  ];

  const data: Item[] = [
    { id: "1", name: "Alpha", count: 42 },
    { id: "2", name: "Beta", count: 10 },
  ];

  it("renders table headers and row data", () => {
    render(<Table data={data} columns={columns} keyField="id" />);
    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Count")).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("triggers onSort when clicking sortable column", () => {
    const onSort = vi.fn();
    render(<Table data={data} columns={columns} keyField="id" onSort={onSort} sortColumn="name" sortDirection="asc" />);
    fireEvent.click(screen.getByText("Name"));
    expect(onSort).toHaveBeenCalledWith("name");
  });

  it("adds scope='col' on all headers and correct aria-sort attributes", () => {
    const { rerender } = render(
      <Table data={data} columns={columns} keyField="id" sortColumn="name" sortDirection="asc" />,
    );

    const nameTh = screen.getByRole("columnheader", { name: /name/i });
    const countTh = screen.getByRole("columnheader", { name: /count/i });

    expect(nameTh).toHaveAttribute("scope", "col");
    expect(countTh).toHaveAttribute("scope", "col");
    expect(nameTh).toHaveAttribute("aria-sort", "ascending");
    expect(countTh).not.toHaveAttribute("aria-sort");
    expect(nameTh).toHaveAttribute("tabindex", "0");
    expect(countTh).not.toHaveAttribute("tabindex");

    rerender(<Table data={data} columns={columns} keyField="id" sortColumn="name" sortDirection="desc" />);
    expect(nameTh).toHaveAttribute("aria-sort", "descending");

    rerender(<Table data={data} columns={columns} keyField="id" sortColumn="other" sortDirection="asc" />);
    expect(nameTh).toHaveAttribute("aria-sort", "none");
  });

  it("triggers onSort on sortable th with Enter and Space keys", () => {
    const onSort = vi.fn();
    render(<Table data={data} columns={columns} keyField="id" onSort={onSort} sortColumn="name" sortDirection="asc" />);
    const nameTh = screen.getByRole("columnheader", { name: /name/i });

    fireEvent.keyDown(nameTh, { key: "Enter" });
    expect(onSort).toHaveBeenCalledWith("name");

    fireEvent.keyDown(nameTh, { key: " " });
    expect(onSort).toHaveBeenCalledTimes(2);

    // Other keys do not trigger onSort
    fireEvent.keyDown(nameTh, { key: "Escape" });
    expect(onSort).toHaveBeenCalledTimes(2);
  });

  it("renders empty state when data is empty", () => {
    render(<Table data={[]} columns={columns} keyField="id" emptyMessage="Custom Empty" />);
    expect(screen.getByText("Custom Empty")).toBeInTheDocument();
  });

  it("handles onRowClick callback", () => {
    const onRowClick = vi.fn();
    render(<Table data={data} columns={columns} keyField="id" onRowClick={onRowClick} />);
    fireEvent.click(screen.getByText("Alpha"));
    expect(onRowClick).toHaveBeenCalledWith(data[0]);
  });
});
