import { useEffect, useState } from "react";
import { getLiveness } from "./lib/api";
import "./app.css";

type ApiState = "checking" | "online" | "offline";

export function App() {
  const [apiState, setApiState] = useState<ApiState>("checking");
  useEffect(() => {
    let active = true;
    getLiveness().then((result) => {
      if (active) setApiState(result.status === "ok" ? "online" : "offline");
    }).catch(() => {
      if (active) setApiState("offline");
    });
    return () => { active = false; };
  }, []);

  return (
    <main className="shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="Ask AI home">
          <span className="brand-mark" aria-hidden="true">A</span><span>Ask AI</span>
        </a>
        <span className={`status status--${apiState}`} role="status" aria-live="polite">
          <span className="status-dot" aria-hidden="true" />API {apiState}
        </span>
      </header>
      <section className="hero" aria-labelledby="title">
        <p className="eyebrow">MULTI-PROVIDER AI WORKSPACE</p>
        <h1 id="title">One place to think with AI.</h1>
        <p className="lead">Ask AI is being built as a secure workspace for conversations across language models.</p>
        <div className="notice"><strong>Foundation release</strong><span>Authentication, model selection, persistent chat, and streaming are planned for upcoming milestones.</span></div>
      </section>
      <footer className="footer">Ask AI · Development foundation</footer>
    </main>
  );
}
