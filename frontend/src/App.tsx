import { useEffect, useState } from "react";
import { AuthScreen } from "./features/auth/AuthScreen";
import { ChatWorkspace } from "./features/chat/ChatWorkspace";
import { exchangeOAuthCode, getAuthProviders, restoreSession } from "./lib/api";
import type { User } from "./lib/types";
import "./app.css";

type AppPhase = "booting" | "signed-out" | "signed-in";

export function App() {
  const [phase, setPhase] = useState<AppPhase>("booting");
  const [user, setUser] = useState<User | null>(null);
  const [providers, setProviders] = useState<string[]>([]);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const handleSessionExpired = () => {
      if (!mounted) return;
      setUser(null);
      setAuthError("Your session has ended. Please sign in again.");
      setPhase("signed-out");
    };
    window.addEventListener("ask-ai:session-expired", handleSessionExpired);
    const finishBootstrap = async () => {
      const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ""));
      const oauthCode = fragment.get("code");
      const oauthError = fragment.get("error");
      if (oauthCode || oauthError) {
        window.history.replaceState({}, document.title, window.location.pathname + window.location.search);
      }

      const providerTask = getAuthProviders().then((items) => {
        if (mounted) setProviders(items);
      }).catch(() => {
        if (mounted) setProviders([]);
      });

      try {
        if (oauthCode) {
          const authenticatedUser = await exchangeOAuthCode(oauthCode);
          if (mounted) {
            setUser(authenticatedUser);
            setPhase("signed-in");
          }
        } else if (oauthError) {
          if (mounted) {
            setAuthError("Your identity provider could not complete sign-in. Please try again.");
            setPhase("signed-out");
          }
        } else {
          const restoredUser = await restoreSession();
          if (mounted) {
            setUser(restoredUser);
            setPhase(restoredUser ? "signed-in" : "signed-out");
          }
        }
      } catch {
        if (mounted) {
          setAuthError("Sign-in could not be completed. Please try again.");
          setPhase("signed-out");
        }
      } finally {
        await providerTask;
      }
    };
    void finishBootstrap();
    return () => {
      mounted = false;
      window.removeEventListener("ask-ai:session-expired", handleSessionExpired);
    };
  }, []);

  if (phase === "booting") {
    return (
      <main className="boot-screen">
        <div className="boot-mark"><span className="brand-mark">✳</span><span>ask<span className="brand-accent">.ai</span></span></div>
        <div className="boot-spinner"/>
        <p>Preparing your workspace</p>
      </main>
    );
  }

  if (phase === "signed-out" || !user) {
    return <AuthScreen providers={providers} initialError={authError} onAuthenticated={(authenticatedUser) => {
      setUser(authenticatedUser);
      setAuthError(null);
      setPhase("signed-in");
    }}/>;
  }

  return <ChatWorkspace user={user} onLogout={() => {
    setUser(null);
    setPhase("signed-out");
  }}/>;
}
