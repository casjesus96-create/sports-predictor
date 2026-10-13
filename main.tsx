import React, { Component, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

class AppErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep the technical details in the browser console for diagnosis,
    // while showing a useful recovery screen to the user.
    console.error("Sports Predictor render error:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main
          role="alert"
          style={{
            minHeight: "100vh",
            display: "grid",
            placeItems: "center",
            padding: 24,
            background: "#07111f",
            color: "#eaf1f8",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          <section
            style={{
              width: "min(100%, 520px)",
              padding: 24,
              border: "1px solid #34516b",
              borderRadius: 16,
              background: "#0b1b2c",
            }}
          >
            <h1 style={{ marginTop: 0 }}>No se pudo mostrar el análisis</h1>
            <p style={{ lineHeight: 1.6, color: "#b9c9d7" }}>
              La pantalla detectó un problema al presentar los datos. La aplicación
              no seguirá en blanco: vuelve a cargarla para recuperar la vista.
              Las predicciones ya guardadas no se borran al recargar.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{
                padding: "12px 16px",
                border: 0,
                borderRadius: 10,
                background: "#e9f0f7",
                color: "#07111f",
                fontWeight: 800,
              }}
            >
              Recargar Sports Predictor
            </button>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}

const root = document.getElementById("root");

if (!root) {
  throw new Error("No se encontró el elemento raíz de Sports Predictor.");
}

createRoot(root).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>,
);
