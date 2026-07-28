import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { CaptureWindow } from "./components/CaptureWindow";
import { inShell, isCaptureWindow } from "./lib/shell";
import "./styles/tokens.css";
import "./styles/reset.css";
import "./styles/app.css";
import "./styles/overlay.css";
import "./styles/shell.css";

const root = document.getElementById("root");
if (!root) throw new Error("Root element missing.");

// Both windows load the same bundle; the query string decides which one this
// is. Under the shell the document also gets a marker, because the journal has
// to inset itself around macOS traffic lights a browser tab does not have.
const capture = isCaptureWindow();
if (inShell()) document.documentElement.dataset.shell = "tauri";
if (capture) document.documentElement.dataset.window = "capture";

createRoot(root).render(<StrictMode>{capture ? <CaptureWindow /> : <App />}</StrictMode>);
