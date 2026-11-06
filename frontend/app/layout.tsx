import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NewsTrace — The Digital News Chronicle",
  description:
    "A source-led newspaper for discovering stories, following journalists and understanding the coverage behind the headlines.",
  applicationName: "NewsTrace",
  icons: { icon: "/favicon.svg" },
};

export const viewport: Viewport = {
  themeColor: "#efe5d2",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
