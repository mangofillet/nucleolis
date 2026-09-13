import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import WorkspaceRouter from "./WorkspaceRouter";

// Fonts are bundled, not fetched. The product guarantees the running app makes
// no network request, so a Google Fonts <link> would break a stated promise.
import "@fontsource/ibm-plex-sans/300.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-serif/400.css";
import "@fontsource/ibm-plex-mono/400.css";

import "./theme.css";
import "./App.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <WorkspaceRouter />
  </StrictMode>,
);
