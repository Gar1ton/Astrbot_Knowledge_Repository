import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { RootProvider } from "fumadocs-ui/provider/next";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Knowledge Repository · 控制台",
  description: "AstrBot 知识库管理控制台",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="zh"
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable}`}
    >
      <body>
        {/* fumadocs-ui RootProvider: search disabled（我们用自定义检索页）; theme 使用 .dark class */}
        <RootProvider
          search={{ enabled: false }}
          theme={{
            attribute: "class",
            defaultTheme: "light",
            enableSystem: true,
            disableTransitionOnChange: true,
          }}
        >
          {children}
        </RootProvider>
      </body>
    </html>
  );
}
