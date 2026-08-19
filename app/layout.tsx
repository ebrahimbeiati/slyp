import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

export const dynamic = "force-dynamic";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Slyp | Payslip insights",
  description: "Track payslips, estimate extra hours, and understand tax impact.",
};

export default function RootLayout({ children }: { readonly children: ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`} style={{ colorScheme: "dark light" }}>
      <body className="min-h-screen bg-[var(--bg-deep)] text-[var(--ink)] antialiased transition-colors duration-300 m-0 p-0">
        {children}
      </body>
    </html>
  );
}
