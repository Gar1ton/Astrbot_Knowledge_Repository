"use client";

import { FormEvent, RefObject, useEffect, useRef, useState } from "react";
import { login } from "@/lib/api";
import { Z } from "@/lib/zLayers";
import styles from "./LoginScreen.module.css";

type Point = readonly [number, number];

type FaceSpec = {
  points: Point[];
  luma: number;
  rows: number;
  cols: number;
  litFrac: number;
  seed: number;
};

function makeRng(seed: number): () => number {
  let value = seed >>> 0;
  return () => {
    value = (Math.imul(value, 1664525) + 1013904223) >>> 0;
    return value / 0xffffffff;
  };
}

function drawFace(ctx: CanvasRenderingContext2D, width: number, height: number, spec: FaceSpec) {
  const { points, luma, rows, cols, litFrac, seed } = spec;
  const rng = makeRng(seed);

  ctx.save();
  ctx.beginPath();
  points.forEach(([x, y], index) => {
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
  ctx.clip();

  const gray = Math.round(luma * 255);
  ctx.fillStyle = `rgb(${gray},${gray},${gray})`;
  ctx.fillRect(0, 0, width, height);

  if (rows > 0 && cols > 0) {
    const xs = Math.min(...points.map(([x]) => x));
    const xe = Math.max(...points.map(([x]) => x));
    const ys = Math.min(...points.map(([, y]) => y));
    const ye = Math.max(...points.map(([, y]) => y));
    const rowHeight = (ye - ys) / rows;
    const colWidth = (xe - xs) / cols;

    ctx.strokeStyle = "rgba(0,0,0,.28)";
    ctx.lineWidth = 1;
    for (let row = 1; row < rows; row += 1) {
      ctx.beginPath();
      ctx.moveTo(xs, ys + row * rowHeight);
      ctx.lineTo(xe, ys + row * rowHeight);
      ctx.stroke();
    }

    ctx.strokeStyle = "rgba(0,0,0,.13)";
    for (let col = 1; col < cols; col += 1) {
      ctx.beginPath();
      ctx.moveTo(xs + col * colWidth, ys);
      ctx.lineTo(xs + col * colWidth, ye);
      ctx.stroke();
    }

    for (let row = 0; row < rows; row += 1) {
      for (let col = 0; col < cols; col += 1) {
        const lit = rng() < litFrac;
        const windowGray = lit ? Math.round((0.54 + rng() * 0.38) * 255) : 9;
        ctx.fillStyle = `rgb(${windowGray},${windowGray},${windowGray})`;
        ctx.fillRect(
          xs + col * colWidth + colWidth * 0.15,
          ys + row * rowHeight + rowHeight * 0.13,
          colWidth * 0.7,
          rowHeight * 0.72
        );
      }
    }
  }

  ctx.restore();
}

function buildScene(width: number, height: number): HTMLCanvasElement {
  const scene = document.createElement("canvas");
  scene.width = width;
  scene.height = height;

  const ctx = scene.getContext("2d");
  if (!ctx) return scene;

  ctx.fillStyle = "#060606";
  ctx.fillRect(0, 0, width, height);

  const faces: FaceSpec[] = [
    { points: [[0, 0], [width * 0.3, 0], [width * 0.41, height], [0, height]], luma: 0.22, rows: 10, cols: 4, litFrac: 0.27, seed: 1001 },
    { points: [[width * 0.26, 0], [width * 0.54, 0], [width * 0.56, height], [width * 0.36, height]], luma: 0.5, rows: 12, cols: 5, litFrac: 0.46, seed: 2002 },
    { points: [[width * 0.51, 0], [width * 0.63, 0], [width * 0.57, height], [width * 0.47, height]], luma: 0.04, rows: 0, cols: 0, litFrac: 0, seed: 3003 },
    { points: [[width * 0.59, 0], [width * 0.82, 0], [width * 0.88, height], [width * 0.53, height]], luma: 0.18, rows: 10, cols: 4, litFrac: 0.21, seed: 4004 },
    { points: [[width * 0.79, 0], [width, 0], [width, height], [width * 0.84, height]], luma: 0.4, rows: 8, cols: 3, litFrac: 0.35, seed: 5005 },
  ];

  faces.forEach((face) => drawFace(ctx, width, height, face));

  ctx.strokeStyle = "rgba(0,0,0,.52)";
  ctx.lineWidth = 3;
  ctx.lineCap = "round";
  [
    [width * 0.3, 0, width * 0.41, height],
    [width * 0.51, 0, width * 0.47, height],
    [width * 0.63, 0, width * 0.57, height],
    [width * 0.79, 0, width * 0.84, height],
  ].forEach(([x1, y1, x2, y2]) => {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  });

  return scene;
}

function buildHalftone(width: number, height: number, dpr: number): HTMLCanvasElement {
  const scene = buildScene(width, height);
  const sceneCtx = scene.getContext("2d");
  const output = document.createElement("canvas");
  output.width = Math.floor(width * dpr);
  output.height = Math.floor(height * dpr);

  const outputCtx = output.getContext("2d");
  if (!sceneCtx || !outputCtx) return output;

  const pixels = sceneCtx.getImageData(0, 0, width, height).data;
  outputCtx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const spacing = 8;
  for (let x = spacing / 2; x < width; x += spacing) {
    for (let y = spacing / 2; y < height; y += spacing) {
      const ix = Math.min(Math.floor(x), width - 1);
      const iy = Math.min(Math.floor(y), height - 1);
      const index = (iy * width + ix) * 4;
      const lum = (pixels[index] * 0.299 + pixels[index + 1] * 0.587 + pixels[index + 2] * 0.114) / 255;
      const tone = 1 - lum;
      const radius = 0.38 + tone * 2.6;

      if (radius < 0.5) continue;

      const alpha = Math.min(0.04 + tone * 0.44, 0.52);
      outputCtx.beginPath();
      outputCtx.arc(x, y, radius, 0, Math.PI * 2);
      outputCtx.fillStyle = `rgba(195,192,186,${alpha.toFixed(2)})`;
      outputCtx.fill();
    }
  }

  return output;
}

function useHalftoneCanvas(canvasRef: RefObject<HTMLCanvasElement | null>) {
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let resizeTimer: number | undefined;

    const draw = () => {
      const width = Math.max(1, Math.floor(window.innerWidth));
      const height = Math.max(1, Math.floor(window.innerHeight));
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const ctx = canvas.getContext("2d");

      if (!ctx) return;

      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;

      const halftone = buildHalftone(width, height, dpr);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(halftone, 0, 0, canvas.width, canvas.height);
    };

    const handleResize = () => {
      if (resizeTimer !== undefined) window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(draw, 90);
    };

    draw();
    window.addEventListener("resize", handleResize);

    return () => {
      if (resizeTimer !== undefined) window.clearTimeout(resizeTimer);
      window.removeEventListener("resize", handleResize);
    };
  }, [canvasRef]);
}

export function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useHalftoneCanvas(canvasRef);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");

    try {
      await login(username, password);
      onLogin();
    } catch {
      setError("Invalid credentials");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.screen} style={{ zIndex: Z.widget }}>
      <canvas ref={canvasRef} className={styles.backdropCanvas} aria-hidden="true" />
      <div className={styles.vignette} aria-hidden="true" />

      <div className={styles.center}>
        <div className={styles.shell}>
          <header className={styles.masthead}>
            <h1 className={styles.title}>KNOWLEDGE ARCH</h1>
            <p className={styles.subtitle}>ASTRBOT · PLUGIN</p>
          </header>

          <div className={styles.rule} aria-hidden="true" />

          <section className={styles.card} aria-label="Knowledge Repository login">
            <form className={styles.form} onSubmit={handleLogin}>
              <label className={styles.field}>
                <span className={styles.fieldLabel}>USERNAME</span>
                <input
                  className={styles.input}
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="admin"
                  autoFocus
                  autoComplete="username"
                  required
                />
              </label>

              <label className={styles.field}>
                <span className={styles.fieldLabel}>PASSWORD</span>
                <input
                  className={styles.input}
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Password"
                  autoComplete="current-password"
                  required
                />
              </label>

              <div className={styles.divider} aria-hidden="true" />

              <button
                className={styles.submitButton}
                type="submit"
                disabled={loading}
                aria-label={loading ? "Signing in" : "Sign in"}
              >
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <line x1="5" y1="12" x2="19" y2="12" />
                  <polyline points="12 5 19 12 12 19" />
                </svg>
              </button>

              {error && <p className={styles.error}>{error}</p>}
            </form>
          </section>

          <p className={styles.footer}>KNOWLEDGE REPOSITORY · CONSOLE</p>
        </div>
      </div>
    </div>
  );
}
