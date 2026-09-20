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

export default function GlobalNav() {
  const pathname = usePathname();
  const [isLater, setIsLater] = useState(false);

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
      <a href="/settings" className={pathname === "/settings" ? "is-active" : undefined} aria-current={pathname === "/settings" ? "page" : undefined}>Instellingen</a>
    </nav>
  );
}
