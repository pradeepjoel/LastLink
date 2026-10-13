import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "LastLink · Airport connection guardian", description: "See if a simulated flight delay leaves time for your scheduled onward tram." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
