import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { initPrePaintAttributes } from "./tokens/storageKeys";
import { tryChunkReloadOnce } from "./utils/chunkReload";

// Synchronously initialize attributes on <html> before first render to prevent theme flashing
initPrePaintAttributes();

// Recover gracefully when a rebuilt frontend replaces hashed Vite chunks under an open tab
window.addEventListener("vite:preloadError", (event) => {
  event.preventDefault();
  tryChunkReloadOnce();
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
