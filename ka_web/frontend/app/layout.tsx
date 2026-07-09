import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import localFont from "next/font/local";
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

const bitcount = localFont({
  src: "./fonts/BitcountGridDouble_Cursive-Regular.ttf",
  variable: "--font-bitcount",
  weight: "400",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Knowledge Arch · 控制台",
  description: "AstrBot 知识库管理控制台",
};

/*
 * 防 FOUC：首帧前同步设置 html[data-theme]（与 next-themes 注入 .dark 同类机制）。
 * 只读迁移判断（读旧键 kr-palette 但不写），持久化迁移由 lib/theme.ts initColorTheme 完成。
 * 兜底分支也必须设置属性——ds-tokens.css 的等特异性级联依赖「data-theme 恒存在」。
 */
const THEME_INIT_SCRIPT = `(function(){var d="nox";try{
var ok=["venus","nox","juno","augustus","selune","folio"];
var t=localStorage.getItem("kr-theme");
if(ok.indexOf(t)<0){var p=localStorage.getItem("kr-palette");t=ok.indexOf(p)>=0?p:d;}
document.documentElement.setAttribute("data-theme",t);
}catch(e){document.documentElement.setAttribute("data-theme",d);}})();`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="zh"
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable} ${bitcount.variable}`}
    >
      <body>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
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
