"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    fetch(`${API}/api/today-plan?timezone=Europe%2FAmsterdam`)
      .then(response => response.ok ? response.json() : [])
      .then((blocks: unknown[]) => {
        if (!cancelled) router.replace(blocks.length > 0 ? "/today" : "/review");
      })
      .catch(() => {
        if (!cancelled) router.replace("/review");
      });
    return () => { cancelled = true; };
  }, [router]);

  return <main className="security-shell"><section className="hero"><p className="eyebrow">ADD</p><h1>Je startpagina wordt klaargezet.</h1><p className="meta" aria-live="polite">Ik controleer je planning voor vandaag…</p></section></main>;
}
