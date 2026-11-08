import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource/ibm-plex-mono/400.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "../shared/tokens.css";
import "./styles.css";
import App from "./App";
import AskMapApp from "./AskMapApp";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {new URLSearchParams(window.location.search).has("legacy") ? <App /> : <AskMapApp />}
  </React.StrictMode>,
);
