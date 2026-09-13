import { lazy, Suspense, useEffect, useState } from "react";
import ResearchWorkspace from "./research/ResearchWorkspace";

const App = lazy(() => import("./App.tsx"));

export default function WorkspaceRouter() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return hash === "#explorer" || hash === "#intervention" ? <Suspense fallback={<p>Loading evidence browser…</p>}><App key={hash} /></Suspense> : <ResearchWorkspace />;
}
