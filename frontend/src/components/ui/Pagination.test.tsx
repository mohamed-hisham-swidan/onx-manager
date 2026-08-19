import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { Pagination, getPageItems } from "./Pagination";

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="location-search">{location.search}</output>;
}

function renderPagination(initialEntry = "/", props: Partial<Parameters<typeof Pagination>[0]> = {}) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Pagination totalItems={25} {...props} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("getPageItems", () => {
  it("returns every page when total <= 7", () => {
    expect(getPageItems(1, 5)).toEqual([1, 2, 3, 4, 5]);
    expect(getPageItems(7, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("windows around the current page with ellipsis for larger totals", () => {
    expect(getPageItems(1, 10)).toEqual([1, 2, "ellipsis", 10]);
    expect(getPageItems(5, 10)).toEqual([1, "ellipsis", 4, 5, 6, "ellipsis", 10]);
    expect(getPageItems(9, 10)).toEqual([1, "ellipsis", 8, 9, 10]);
    expect(getPageItems(10, 10)).toEqual([1, "ellipsis", 9, 10]);
  });
});

describe("Pagination", () => {
  it("renders nothing when there is only one page", () => {
    renderPagination("/", { totalItems: 20 });
    expect(screen.queryByTestId("pagination")).not.toBeInTheDocument();
  });

  it("renders numbered pages with the current page highlighted", () => {
    renderPagination("/");
    expect(screen.getByRole("button", { name: "Page 1", current: "page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Page 2" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();
  });

  it("highlights the page from the URL param and disables prev/next accordingly", () => {
    renderPagination("/?page=2");
    expect(screen.getByRole("button", { name: "Page 2", current: "page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("updates the URL page param when a page number is clicked, preserving other params", () => {
    renderPagination("/?q=essentials&type=plugin");
    fireEvent.click(screen.getByRole("button", { name: "Page 2" }));

    expect(screen.getByRole("button", { name: "Page 2", current: "page" })).toBeInTheDocument();
    expect(screen.getByLabelText("location-search")).toHaveTextContent("q=essentials");
    expect(screen.getByLabelText("location-search")).toHaveTextContent("type=plugin");
    expect(screen.getByLabelText("location-search")).toHaveTextContent("page=2");
  });

  it("moves forward and backward with the arrow buttons", () => {
    renderPagination("/?page=2", { totalItems: 60 });
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));

    expect(screen.getByRole("button", { name: "Page 2", current: "page" })).toBeInTheDocument();
  });

  it("clamps an out-of-range page param to the last page", () => {
    renderPagination("/?page=99");
    expect(screen.getByRole("button", { name: "Page 2", current: "page" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("renders ellipsis separators for many pages", () => {
    renderPagination("/", { totalItems: 200 });
    expect(screen.getAllByText("...")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Page 10" })).toBeInTheDocument();
  });
});