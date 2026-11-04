import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { initPrePaintAttributes } from "./tokens/storageKeys";

// Synchronously initialize attributes on <html> before first render to prevent theme flashing
initPrePaintAttributes();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
