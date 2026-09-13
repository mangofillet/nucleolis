import { lazy, Suspense, useEffect, useState } from "react";
import ResearchWorkspace from "./research/ResearchWorkspace";

const App = lazy(() => import("./App.tsx"));
const ResilienceView = lazy(() => import("./showcase/ResilienceView"));

export default function WorkspaceRouter() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const update = () => setHash(window.location.hash);
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);

  if (hash === "#explorer" || hash === "#intervention") {
    return (
      <Suspense fallback={<p>Loading evidence browser…</p>}>
        <App key={hash} />
      </Suspense>
    );
  }
  if (hash === "#resilience") {
    return (
      <Suspense fallback={<p>Loading mechanism axes…</p>}>
        <ResilienceView />
      </Suspense>
    );
  }
  return <ResearchWorkspace />;
}
