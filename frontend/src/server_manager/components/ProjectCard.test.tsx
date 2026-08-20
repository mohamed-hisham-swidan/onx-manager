import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ProjectCard } from "./ProjectCard";
import type { PluginSearchResultResponse } from "@/types";

const mockProject: PluginSearchResultResponse = {
  project_id: "essentialsx",
  slug: "essentialsx",
  title: "EssentialsX",
  description: "Essential commands",
  author: "Essentials Team",
  project_types: ["plugin"],
  downloads: 1_200_000,
  follows: 100,
  icon_url: "",
  latest_version_id: "v1",
  categories: ["management", "economy"],
  loaders: ["paper", "spigot"],
  client_side: "unsupported",
  server_side: "required",
  date_modified: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
  color: null,
};

function renderCard(
  project: PluginSearchResultResponse = mockProject,
  searchParams = new URLSearchParams(),
  onInstall = vi.fn(),
) {
  return render(
    <MemoryRouter>
      <ProjectCard project={project} searchParams={searchParams} onInstall={onInstall} />
    </MemoryRouter>,
  );
}

describe("ProjectCard", () => {
  it("renders title, author and description", () => {
    renderCard();
    expect(screen.getByText("EssentialsX")).toBeInTheDocument();
    expect(screen.getByText(/by Essentials Team/)).toBeInTheDocument();
    expect(screen.getByText("Essential commands")).toBeInTheDocument();
  });

  it("renders loader, category and environment pills", () => {
    renderCard();
    expect(screen.getByText("Paper")).toBeInTheDocument();
    expect(screen.getByText("Spigot")).toBeInTheDocument();
    expect(screen.getByText("management")).toBeInTheDocument();
    expect(screen.getByText("economy")).toBeInTheDocument();
    expect(screen.getByText("Server-side")).toBeInTheDocument();
  });

  it("renders formatted downloads, follows and relative updated time", () => {
    renderCard();
    expect(screen.getByText("1.2M")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText(/Updated 3d ago/)).toBeInTheDocument();
  });

  it("links to the project detail page preserving search params", () => {
    renderCard(mockProject, new URLSearchParams("q=essentials&type=plugin"));
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/marketplace/essentialsx?q=essentials&type=plugin");
  });

  it("invokes onInstall when the Install button is clicked", () => {
    const onInstall = vi.fn();
    renderCard(mockProject, new URLSearchParams(), onInstall);
    fireEvent.click(screen.getByRole("button", { name: /Install/i }));
    expect(onInstall).toHaveBeenCalledWith(mockProject);
  });

  it("renders no updated time when date_modified is missing", () => {
    renderCard({ ...mockProject, date_modified: "" });
    expect(screen.queryByText(/Updated/)).not.toBeInTheDocument();
  });

  it("tolerates missing loaders and categories", () => {
    renderCard({ ...mockProject, loaders: [], categories: [] });
    expect(screen.queryByText("Paper")).not.toBeInTheDocument();
    expect(screen.queryByText("management")).not.toBeInTheDocument();
  });
});