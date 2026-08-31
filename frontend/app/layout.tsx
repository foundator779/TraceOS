import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TraceOS — Zero-trust forensics fleet",
  description: "Governed autonomous digital forensics for enterprise investigations.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
