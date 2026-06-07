import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI Content Production Agent",
  description: "Brief in → prompt → image → quality score → human approval.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
