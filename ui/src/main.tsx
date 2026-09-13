import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import WorkspaceRouter from "./WorkspaceRouter";
import "./App.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <WorkspaceRouter />
  </StrictMode>,
);
