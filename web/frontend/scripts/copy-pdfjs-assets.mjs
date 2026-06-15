// 把 pdfjs-dist 自带的运行时资源同步到 public/pdfjs/，供阅读面板 getDocument 加载。
// pdfjs v6 把 JBIG2/JPEG2000 图像解码器迁到了 WASM，扫描件 PDF 需要 wasmUrl 才能渲染图像。
// public/ 内容经 next export → out/ → tools/sync_frontend.py → pages/，dev 与 prod 均可在 /pdfjs/... 访问。
import { cpSync, rmSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const pkgDir = resolve(here, "..", "node_modules", "pdfjs-dist");
const destRoot = resolve(here, "..", "public", "pdfjs");

const dirs = ["wasm", "cmaps", "standard_fonts"];

if (!existsSync(pkgDir)) {
  console.error(`[copy-pdfjs-assets] pdfjs-dist 未安装：${pkgDir}`);
  process.exit(1);
}

// 幂等：先清空再拷贝，确保与已安装版本一致。
rmSync(destRoot, { recursive: true, force: true });
mkdirSync(destRoot, { recursive: true });

for (const dir of dirs) {
  const src = resolve(pkgDir, dir);
  if (!existsSync(src)) {
    console.warn(`[copy-pdfjs-assets] 跳过缺失目录：${src}`);
    continue;
  }
  cpSync(src, resolve(destRoot, dir), { recursive: true });
  console.log(`[copy-pdfjs-assets] ${dir} → public/pdfjs/${dir}`);
}
