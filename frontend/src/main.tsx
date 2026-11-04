import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// Synchronously initialize attributes on <html> before first render to prevent theme flashing
try {
  const mode =
    localStorage.getItem("theme") ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const skin = localStorage.getItem("skin") || "graphite";
  const density = localStorage.getItem("density") || "comfortable";

  document.documentElement.setAttribute("data-mode", mode);
  document.documentElement.setAttribute("data-skin", skin);
  document.documentElement.setAttribute("data-density", density);
  if (mode === "dark") {
    document.documentElement.classList.add("dark");
  } else {
    document.documentElement.classList.remove("dark");
  }
} catch {
  // Graceful fallback if localStorage is unavailable
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
