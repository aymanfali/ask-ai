import { useState, type FormEvent } from "react";
import { ApiError, login, register, startOAuth } from "../../lib/api";
import { Icon } from "../../components/Icon";
import type { User } from "../../lib/types";

type AuthMode = "login" | "register";

interface AuthScreenProps {
  providers: string[];
  initialError?: string | null;
  onAuthenticated: (user: User) => void;
}

function readableError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "invalid_credentials") return "The email or password is incorrect.";
    if (error.code === "email_unavailable") return "An account cannot be created with this email address.";
    if (error.code === "registration_disabled") return "New account registration is currently disabled.";
    if (error.status === 429) return "Too many attempts. Please wait a few minutes and try again.";
    return error.message;
  }
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

export function AuthScreen({ providers, initialError, onAuthenticated }: AuthScreenProps) {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = mode === "login"
        ? await login(email.trim(), password)
        : await register(email.trim(), password, displayName.trim());
      onAuthenticated(user);
    } catch (caught) {
      setError(readableError(caught));
    } finally {
      setBusy(false);
    }
  };

  const toggleMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setError(null);
  };

  return (
    <main className="auth-layout">
      <section className="auth-story" aria-label="Ask AI introduction">
        <a className="brand brand--large" href="/" aria-label="Ask AI home">
          <span className="brand-mark"><Icon name="sparkles" size={20}/></span>
          <span>ask<span className="brand-accent">.ai</span></span>
        </a>
        <div className="auth-story__copy">
          <span className="eyebrow"><span className="eyebrow-dot"/> YOUR AI, IN ONE WORKSPACE</span>
          <h1>Ideas deserve<br/><span>better answers.</span></h1>
          <p>One thoughtful workspace for conversations across the models you choose.</p>
        </div>
        <div className="auth-story__bottom">
          <div className="trust-mark"><Icon name="shield" size={16}/> Your conversations stay yours.</div>
          <span>Ask AI · Multi-provider workspace</span>
        </div>
        <div className="story-orb story-orb--one" aria-hidden="true"/>
        <div className="story-orb story-orb--two" aria-hidden="true"/>
      </section>

      <section className="auth-panel">
        <div className="auth-panel__inner">
          <div className="auth-mobile-brand"><span className="brand-mark"><Icon name="sparkles" size={18}/></span>ask<span className="brand-accent">.ai</span></div>
          <div className="auth-heading">
            <span className="auth-kicker">WELCOME {mode === "login" ? "BACK" : "ABOARD"}</span>
            <h2>{mode === "login" ? "Sign in to Ask AI" : "Create your account"}</h2>
            <p>{mode === "login" ? "Pick up where your thinking left off." : "Your model workspace starts here."}</p>
          </div>

          <div className="auth-tabs" role="tablist" aria-label="Authentication mode">
            <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "is-active" : ""} onClick={() => toggleMode("login")}>Sign in</button>
            <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "is-active" : ""} onClick={() => toggleMode("register")}>Create account</button>
          </div>

          {providers.length > 0 && (
            <div className="oauth-options">
              {providers.includes("google") && <button type="button" className="oauth-button" onClick={() => startOAuth("google")}><span className="google-g">G</span> {mode === "register" ? "Sign up with Google" : "Sign in with Google"}</button>}
              {providers.includes("apple") && <button type="button" className="oauth-button" onClick={() => startOAuth("apple")}><span className="apple-mark">●</span> {mode === "register" ? "Sign up with Apple" : "Sign in with Apple"}</button>}
            </div>
          )}

          {providers.length > 0 && <div className="auth-divider"><span/>{mode === "register" ? "or sign up with email" : "or sign in with email"}<span/></div>}

          <form className="auth-form" onSubmit={submit}>
            {mode === "register" && (
              <label className="field">
                <span>Name <span className="field-optional">(optional)</span></span>
                <input autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="How should we address you?" maxLength={120}/>
              </label>
            )}
            <label className="field">
              <span>Email address</span>
              <input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" required maxLength={320}/>
            </label>
            <label className="field">
              <span>Password</span>
              <input type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={mode === "register" ? "At least 12 characters" : "Enter your password"} required minLength={mode === "register" ? 12 : 1} maxLength={128}/>
            </label>
            {mode === "register" && <p className="form-hint">Use at least 12 characters. A password manager is recommended.</p>}
            {error && <div className="form-error" role="alert"><Icon name="shield" size={16}/>{error}</div>}
            <button className="primary-button auth-submit" type="submit" disabled={busy || !email.trim() || !password}>
              {busy ? <span className="spinner"/> : <>{mode === "login" ? "Sign in" : "Create account"}<Icon name="arrow" size={17}/></>}
            </button>
          </form>
          <p className="auth-legal">By continuing, you agree to use Ask AI responsibly. Your provider credentials are never exposed to this browser.</p>
        </div>
      </section>
    </main>
  );
}
