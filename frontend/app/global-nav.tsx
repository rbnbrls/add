"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

type NavItem = { label: string; href: string; key: string };

const items: NavItem[] = [
  { label: "Inbox", href: "/review", key: "inbox" },
  { label: "Later", href: "/views?unplanned=true", key: "later" },
  { label: "Gepland", href: "/today", key: "planned" },
  { label: "Dagreview", href: "/daily-review", key: "review" },
];

export default function GlobalNav({ authenticated, onLogout }: { authenticated: boolean; onLogout: () => void | Promise<void> }) {
  const pathname = usePathname();
  const [isLater, setIsLater] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackType, setFeedbackType] = useState<"bug" | "feature">("feature");
  const [feedbackTitle, setFeedbackTitle] = useState("");
  const [feedbackDescription, setFeedbackDescription] = useState("");
  const [feedbackState, setFeedbackState] = useState<"idle" | "sending" | "success" | "error">("idle");
  const [feedbackMessage, setFeedbackMessage] = useState("");

  useEffect(() => {
    setIsLater(pathname === "/views" && new URLSearchParams(window.location.search).get("unplanned") === "true");
  }, [pathname]);

  function isActive(key: string) {
    if (key === "later") return isLater;
    if (key === "inbox") return pathname === "/review";
    if (key === "planned") return pathname === "/today";
    if (key === "review") return pathname === "/daily-review";
    return false;
  }

  function closeFeedback() {
    if (feedbackState !== "sending") setFeedbackOpen(false);
  }

  async function submitFeedback(event: React.FormEvent) {
    event.preventDefault();
    setFeedbackState("sending");
    setFeedbackMessage("");
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type: feedbackType, title: feedbackTitle, description: feedbackDescription }),
      });
      const result = await response.json().catch(() => null);
      if (!response.ok) {
        setFeedbackState("error");
        setFeedbackMessage(result?.detail || "Feedback kon niet worden verzonden.");
        return;
      }
      setFeedbackState("success");
      setFeedbackMessage(result?.issue_url || "Je feedback staat klaar als GitHub issue.");
    } catch {
      setFeedbackState("error");
      setFeedbackMessage("De verbinding met ADD lukte niet. Probeer het opnieuw.");
    }
  }

  function resetFeedback() {
    setFeedbackOpen(false);
    setFeedbackState("idle");
    setFeedbackMessage("");
    setFeedbackTitle("");
    setFeedbackDescription("");
  }

  return (
    <nav className="global-nav" aria-label="Workflow navigatie">
      <a className="global-brand" href="/overview">ADD</a>
      <div className="global-flow">
        {items.map((item, index) => (
          <span className="global-flow-item" key={item.key}>
            {index > 0 && <span className="global-flow-arrow" aria-hidden="true">→</span>}
            <a href={item.href} className={isActive(item.key) ? "is-active" : undefined} aria-current={isActive(item.key) ? "page" : undefined}>
              {item.label}
            </a>
          </span>
        ))}
      </div>
      <div className="global-nav-tools">
        {authenticated && <button className="feedback-button" type="button" onClick={() => { setFeedbackState("idle"); setFeedbackOpen(true); }} aria-haspopup="dialog">Feedback</button>}
        <a href="/settings" className={pathname === "/settings" ? "is-active" : undefined} aria-current={pathname === "/settings" ? "page" : undefined}>Instellingen</a>
        {authenticated && <button className="feedback-button" type="button" onClick={() => void onLogout()}>Uitloggen</button>}
      </div>
      {feedbackOpen && <div className="feedback-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeFeedback(); }}>
        <section className="feedback-modal" role="dialog" aria-modal="true" aria-labelledby="feedback-title-heading">
          {feedbackState === "success" ? <div className="feedback-success"><p className="eyebrow">VERZONDEN</p><h2 id="feedback-title-heading">Dank je.</h2><p className="meta">Je feedback is als GitHub issue aangemaakt.</p>{feedbackMessage.startsWith("http") && <a className="secondary-link" href={feedbackMessage} target="_blank" rel="noreferrer">Issue bekijken →</a>}<button type="button" className="quiet" onClick={resetFeedback}>Sluiten</button></div> : <form onSubmit={submitFeedback}>
            <div className="feedback-modal-heading"><div><p className="eyebrow">SAMEN BETER</p><h2 id="feedback-title-heading">Wat kan scherper?</h2></div><button type="button" className="feedback-close" onClick={closeFeedback} aria-label="Feedback sluiten">×</button></div>
            <p className="meta">Een korte melding helpt ADD rustig verbeteren.</p>
            <label>Soort<select value={feedbackType} onChange={(event) => setFeedbackType(event.target.value as "bug" | "feature")}><option value="feature">Idee of verbetering</option><option value="bug">Iets werkt niet</option></select></label>
            <label>Titel<input required maxLength={160} value={feedbackTitle} onChange={(event) => setFeedbackTitle(event.target.value)} placeholder="Bijvoorbeeld: sneller naar Vandaag" /></label>
            <label>Omschrijving<textarea required maxLength={4000} rows={6} value={feedbackDescription} onChange={(event) => setFeedbackDescription(event.target.value)} placeholder="Wat wilde je doen, en wat gebeurde er?" /></label>
            {feedbackState === "error" && <p className="feedback-error" role="alert">{feedbackMessage}</p>}
            <div className="feedback-actions"><button type="button" className="secondary" onClick={closeFeedback}>Annuleren</button><button type="submit" disabled={feedbackState === "sending"}>{feedbackState === "sending" ? "Verzenden…" : "Feedback versturen"}</button></div>
          </form>}
        </section>
      </div>}
    </nav>
  );
}
