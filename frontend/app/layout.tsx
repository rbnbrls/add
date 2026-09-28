import "./style.css";
import "./accessibility.css";
import "./llm-settings.css";
import "./task-detail.css";
import "./planner.css";
import type { Metadata } from "next";
import AuthGate from "./auth-gate";
import ServiceWorkerRegister from "./sw-register";

export const metadata: Metadata = { title: "ADD — Activation · Do · Done", description: "Eén uitvoerbare volgende actie.", manifest: "/manifest.webmanifest" };
export default function Layout({ children }: { children: React.ReactNode }) { return <html lang="nl"><body><ServiceWorkerRegister/><a className="skip-link" href="#main-content">Ga naar hoofdinhoud</a><div id="main-content"><AuthGate>{children}</AuthGate></div></body></html>; }
