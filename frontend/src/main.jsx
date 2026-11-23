import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

function App() {
  const [status, setStatus] = useState("Checking connection…");

  useEffect(() => {
    async function checkConnection() {
      try {
        const response = await fetch("/api/health/");
        const data = await response.json();

        if (!response.ok || data.database !== "ok") {
          throw new Error("Database check failed");
        }

        setStatus("PostgreSQL connected.");
      } catch {
        setStatus("Connection failed. Check the Docker logs.");
      }
    }

    checkConnection();
  }, []);

  return (
    <main>
     <h1>TopTenPercent </h1>
      <p>{status}</p>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);