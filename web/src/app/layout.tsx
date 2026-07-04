import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/providers";

export const metadata: Metadata = {
  title: "FinAdvisor",
  description: "AI financial advisor for MOEX markets",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body className="bg-gray-950 text-gray-100 min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
