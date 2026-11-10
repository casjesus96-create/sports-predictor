import { useCallback, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";

type AuthStatus = "checking" | "authenticated" | "mfa" | "anonymous" | "unavailable";

export default function AuthGate({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [ownerEmail, setOwnerEmail] = useState("");
  const [factorId, setFactorId] = useState("");
  const [setupNeeded, setSetupNeeded] = useState(false);
  const [setupSecret, setSetupSecret] = useState("");
  const [otp, setOtp] = useState("");

  const checkSession = useCallback(async () => {
    setStatus("checking");
    try {
      const response = await fetch("/auth/status", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error("No fue posible comprobar la sesión.");
      const data = await response.json();
      setOwnerEmail(data.email || "");
      setFactorId(data.mfa_factor_id || "");
      setSetupNeeded(Boolean(data.mfa_setup_needed));
      setStatus(data.authenticated ? "authenticated" : "anonymous");
      setMessage("");
    } catch {
      setStatus("unavailable");
      setMessage("No se pudo verificar la conexión segura. Intenta nuevamente.");
    }
  }, []);

  useEffect(() => {
    void checkSession();
  }, [checkSession]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || "Correo o contraseña incorrectos.");
      }
      setPassword("");
      setOwnerEmail(data.email || email.trim());
      await checkSession();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No fue posible iniciar sesión.");
    } finally {
      setBusy(false);
    }
  }

  async function handleMfaSetup() {
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/auth/mfa/enroll", { method: "POST", credentials: "same-origin" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "No se pudo activar el segundo factor.");
      setFactorId(data.factor_id || "");
      setSetupSecret(data.secret || "");
      setSetupNeeded(false);
      setMessage("Guarda la clave en tu aplicación autenticadora y después introduce el código.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo configurar el segundo factor.");
    } finally {
      setBusy(false);
    }
  }

  async function handleMfaVerify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/auth/mfa/verify", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ factor_id: factorId, code: otp }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Código incorrecto o vencido.");
      setOtp("");
      setSetupSecret("");
      setStatus("authenticated");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo verificar el código.");
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    setBusy(true);
    try {
      await fetch("/auth/logout", {
        method: "POST",
        credentials: "same-origin",
      });
    } finally {
      setPassword("");
      setOwnerEmail("");
      setFactorId("");
      setSetupNeeded(false);
      setSetupSecret("");
      setOtp("");
      setMessage("");
      setStatus("anonymous");
      setBusy(false);
    }
  }

  if (status === "mfa") {
    return (
      <main style={pageStyle}>
        <section style={cardStyle}>
          <div style={{ fontSize: 13, letterSpacing: 2, color: "#60a5fa", fontWeight: 800 }}>VERIFICACIÓN ADICIONAL</div>
          <h1 style={{ margin: "10px 0 6px", fontSize: 26 }}>Protege tu cuenta</h1>
          <p style={{ color: "#a9bdcf", lineHeight: 1.6 }}>{ownerEmail}. Para abrir Sports Predictor debes completar la autenticación de dos factores.</p>
          {setupNeeded ? (
            <>
              <p style={{ color: "#cbd5e1", lineHeight: 1.6 }}>Configura una aplicación autenticadora compatible con TOTP, como Google Authenticator, Microsoft Authenticator o 1Password.</p>
              <button type="button" disabled={busy} onClick={handleMfaSetup} style={buttonStyle}>{busy ? "Preparando…" : "Activar segundo factor"}</button>
            </>
          ) : (
            <>
              {setupSecret && (
                <div style={{ margin: "16px 0", padding: 14, borderRadius: 10, background: "#07111f", border: "1px solid #405a73" }}>
                  <div style={{ color: "#93c5fd", fontSize: 12, fontWeight: 800, marginBottom: 8 }}>CLAVE DE CONFIGURACIÓN · GUARDA EN UN LUGAR SEGURO</div>
                  <code style={{ color: "#fff", overflowWrap: "anywhere", userSelect: "all" }}>{setupSecret}</code>
                </div>
              )}
              <form onSubmit={handleMfaVerify}>
                <label htmlFor="sp-otp" style={labelStyle}>Código de seis dígitos</label>
                <input
                  id="sp-otp" type="text" inputMode="numeric" autoComplete="one-time-code"
                  pattern="[0-9]{6}" maxLength={6} required value={otp}
                  onChange={(event) => setOtp(event.target.value.replace(/[^0-9]/g, "").slice(0, 6))}
                  style={inputStyle}
                />
                <button type="submit" disabled={busy || !factorId || otp.length !== 6} style={{ ...buttonStyle, opacity: busy ? .65 : 1 }}>
                  {busy ? "Verificando…" : "Verificar y entrar"}
                </button>
              </form>
            </>
          )}
          {message && <p role="alert" style={{ color: "#fbbf24", lineHeight: 1.5 }}>{message}</p>}
          <button type="button" onClick={handleLogout} disabled={busy} style={{ ...buttonStyle, background: "#334155" }}>Cancelar y cerrar sesión</button>
        </section>
      </main>
    );
  }

  if (status === "authenticated") {
    return (
      <>
        <div
          style={{
            display: "flex", justifyContent: "flex-end", alignItems: "center",
            gap: 12, padding: "8px 16px", color: "#94a3b8", fontSize: 12,
          }}
        >
          <span>{ownerEmail}</span>
          <button
            type="button"
            onClick={handleLogout}
            disabled={busy}
            style={{
              border: "1px solid #475569", borderRadius: 8, padding: "8px 12px",
              background: "#0f172a", color: "#e2e8f0", fontWeight: 700,
            }}
          >
            Cerrar sesión
          </button>
        </div>
        {children}
      </>
    );
  }

  return (
    <main
      style={{
        minHeight: "100vh", display: "grid", placeItems: "center", padding: 20,
        background: "radial-gradient(circle at top, #142b45 0%, #07111f 55%)",
        color: "#eaf1f8", fontFamily: "system-ui, sans-serif",
      }}
    >
      <section
        style={{
          width: "min(100%, 420px)", boxSizing: "border-box", padding: 28,
          border: "1px solid #29435d", borderRadius: 18, background: "#0b1b2c",
          boxShadow: "0 24px 70px rgba(0,0,0,.35)",
        }}
      >
        <div style={{ fontSize: 13, letterSpacing: 2, color: "#60a5fa", fontWeight: 800 }}>
          ACCESO PRIVADO
        </div>
        <h1 style={{ margin: "10px 0 6px", fontSize: 28 }}>Sports Predictor</h1>
        <p style={{ margin: "0 0 24px", color: "#a9bdcf", lineHeight: 1.6 }}>
          Inicia sesión con la cuenta autorizada para acceder al panel y sus análisis.
        </p>
        {status === "checking" ? (
          <p role="status">Verificando sesión segura…</p>
        ) : status === "unavailable" ? (
          <>
            <p role="alert" style={{ color: "#fbbf24" }}>{message}</p>
            <button type="button" onClick={() => void checkSession()} style={buttonStyle}>
              Reintentar
            </button>
          </>
        ) : (
          <form onSubmit={handleLogin}>
            <label htmlFor="sp-email" style={labelStyle}>Correo autorizado</label>
            <input
              id="sp-email" type="email" autoComplete="username" required
              value={email} onChange={(event) => setEmail(event.target.value)}
              style={inputStyle}
            />
            <label htmlFor="sp-password" style={labelStyle}>Contraseña</label>
            <input
              id="sp-password" type="password" autoComplete="current-password" required
              value={password} onChange={(event) => setPassword(event.target.value)}
              style={inputStyle}
            />
            {message && <p role="alert" style={{ color: "#fca5a5", lineHeight: 1.5 }}>{message}</p>}
            <button type="submit" disabled={busy} style={{ ...buttonStyle, opacity: busy ? .65 : 1 }}>
              {busy ? "Verificando…" : "Iniciar sesión"}
            </button>
          </form>
        )}
        <p style={{ margin: "20px 0 0", color: "#71869a", fontSize: 12, lineHeight: 1.5 }}>
          Acceso individual. No existe registro público de cuentas.
        </p>
      </section>
    </main>
  );
}

const pageStyle: React.CSSProperties = {
  minHeight: "100vh", display: "grid", placeItems: "center", padding: 20,
  background: "radial-gradient(circle at top, #142b45 0%, #07111f 55%)",
  color: "#eaf1f8", fontFamily: "system-ui, sans-serif",
};
const cardStyle: React.CSSProperties = {
  width: "min(100%, 420px)", boxSizing: "border-box", padding: 28,
  border: "1px solid #29435d", borderRadius: 18, background: "#0b1b2c",
  boxShadow: "0 24px 70px rgba(0,0,0,.35)",
};
const labelStyle: React.CSSProperties = {
  display: "block", margin: "16px 0 7px", color: "#cbd5e1", fontSize: 13, fontWeight: 700,
};
const inputStyle: React.CSSProperties = {
  width: "100%", boxSizing: "border-box", minHeight: 46, padding: "11px 12px",
  border: "1px solid #405a73", borderRadius: 9, background: "#07111f",
  color: "#f8fafc", fontSize: 16,
};
const buttonStyle: React.CSSProperties = {
  width: "100%", minHeight: 46, marginTop: 18, padding: "12px 14px",
  border: 0, borderRadius: 9, background: "#2563eb", color: "#fff",
  fontWeight: 800, cursor: "pointer",
};
