import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Finn — AI Assistant for MOEX Markets",
    short_name: "Finn",
    description: "AI financial advisor for MOEX markets",
    start_url: "/",
    display: "standalone",
    background_color: "#1a1a2e",
    theme_color: "#16213e",
    icons: [
      { src: "/icons/icon-192.svg", sizes: "192x192", type: "image/svg+xml" },
      { src: "/icons/icon-512.svg", sizes: "512x512", type: "image/svg+xml" },
    ],
  };
}
