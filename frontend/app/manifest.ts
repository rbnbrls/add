import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "ADD — Activation · Do · Done",
    short_name: "ADD",
    description: "Eén uitvoerbare volgende actie.",
    start_url: "/",
    display: "standalone",
    background_color: "#f6f3ed",
    theme_color: "#17202a",
    lang: "nl",
    shortcuts: [
      { name: "Snel vastleggen", short_name: "Capture", description: "Zet iets direct in de ADD-inbox", url: "/intake?quick=1" },
      { name: "Volgende actie", short_name: "NU", description: "Open de volgende uitvoerbare actie", url: "/" },
    ],
  };
}
