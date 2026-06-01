"use client";

import React, { useEffect, useRef, useState } from "react";
import { DotField } from "./DotField";
import { SunBloom } from "./SunBloom";

interface AtmosphereProps {
  variant?: "default" | "minimal" | "login";
  sun?: boolean;
  follow?: boolean;
}

export function Atmosphere({ variant = "default", sun = false, follow = true }: AtmosphereProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const layersRef = useRef<HTMLDivElement>(null);
  
  // Mouse target and current LERP positions
  const mouseRef = useRef({ tx: 0.5, ty: 0.5, cx: 0.5, cy: 0.5 });
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    // Check prefers-reduced-motion
    const mediaQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mediaQuery.matches);
    
    const handleMediaChange = (e: MediaQueryListEvent) => {
      setReducedMotion(e.matches);
    };
    mediaQuery.addEventListener("change", handleMediaChange);

    // Track mouse coordinates relative to viewport (or container)
    const handleMouseMove = (e: MouseEvent) => {
      if (mediaQuery.matches || !follow) return;
      
      const container = containerRef.current;
      if (!container) return;

      const rect = container.getBoundingClientRect();
      const tx = (e.clientX - rect.left) / (rect.width || 1);
      const ty = (e.clientY - rect.top) / (rect.height || 1);

      mouseRef.current.tx = Math.max(0, Math.min(1, tx));
      mouseRef.current.ty = Math.max(0, Math.min(1, ty));
    };

    window.addEventListener("mousemove", handleMouseMove);

    // Animation Loop
    let animId: number;
    const updateMotion = () => {
      if (mediaQuery.matches) {
        // Just set static positions if motion reduced
        if (glowRef.current) {
          glowRef.current.style.transform = `translate3d(calc(50% - 180px), calc(50% - 180px), 0)`;
        }
        return;
      }

      const m = mouseRef.current;
      // Linear interpolation: LERP ≈ 0.06
      m.cx = m.cx + (m.tx - m.cx) * 0.06;
      m.cy = m.cy + (m.ty - m.cy) * 0.06;

      const container = containerRef.current;
      if (container) {
        const rect = container.getBoundingClientRect();
        
        // 1. Update Follow Glow
        if (glowRef.current && follow) {
          const posX = m.cx * rect.width - 180;
          const posY = m.cy * rect.height - 180;
          glowRef.current.style.transform = `translate3d(${posX}px, ${posY}px, 0)`;
        }

        // 2. Update Parallax Layers
        if (layersRef.current) {
          const fxLayers = layersRef.current.querySelectorAll<HTMLDivElement>("[data-depth]");
          fxLayers.forEach((layer) => {
            const depth = parseFloat(layer.getAttribute("data-depth") || "0");
            // Maximum parallax travel is 30px
            const maxTravel = 30;
            const px = (m.cx - 0.5) * maxTravel * depth;
            const py = (m.cy - 0.5) * maxTravel * depth;
            layer.style.translate = `${px}px ${py}px`;
          });
        }
      }

      animId = requestAnimationFrame(updateMotion);
    };

    animId = requestAnimationFrame(updateMotion);

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      mediaQuery.removeEventListener("change", handleMediaChange);
      cancelAnimationFrame(animId);
    };
  }, [follow]);

  return (
    <div
      ref={containerRef}
      aria-hidden
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        pointerEvents: "none",
        zIndex: 0,
      }}
    >
      {/* Styles for aurora shifts */}
      <style dangerouslySetInnerHTML={{ __html: `
        @keyframes auroraShift1 {
          0%, 100% { transform: translate(0px, 0px) scale(1); }
          33% { transform: translate(30px, -40px) scale(1.08); }
          66% { transform: translate(-20px, 20px) scale(0.95); }
        }
        @keyframes auroraShift2 {
          0%, 100% { transform: translate(0px, 0px) scale(1.05); }
          50% { transform: translate(-40px, 30px) scale(0.92); }
        }
      `}} />

      {/* 2.1 Follow Mouse Glow */}
      {follow && !reducedMotion && (
        <div
          ref={glowRef}
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: 360,
            height: 360,
            opacity: 0.5,
            filter: "blur(8px)",
            borderRadius: "50%",
            background: "radial-gradient(circle at 50% 50%, var(--glow) 0%, color-mix(in srgb, var(--accent) 5%, transparent) 40%, transparent 68%)",
            willChange: "transform",
            zIndex: 2,
          }}
        />
      )}

      {/* Parallax Group Layer */}
      <div ref={layersRef} style={{ position: "absolute", inset: 0, zIndex: 1 }}>
        {/* 2.2.1 Aurora Layer (2-3 large spots shifting) */}
        {variant !== "minimal" && (
          <div
            style={{
              position: "absolute",
              inset: 0,
              opacity: 0.28,
            }}
          >
            {/* Spot 1 (Accent Soft) */}
            <div
              className="fx-layer"
              data-depth="0.25"
              style={{
                position: "absolute",
                top: "-10%",
                left: "15%",
                width: "60%",
                height: "60%",
                borderRadius: "50%",
                background: "radial-gradient(circle, var(--accent-soft) 0%, transparent 70%)",
                filter: "blur(40px)",
                animation: "auroraShift1 25s ease-in-out infinite",
                willChange: "translate",
              }}
            />
            {/* Spot 2 (Accent 2 Soft) */}
            <div
              className="fx-layer"
              data-depth="0.4"
              style={{
                position: "absolute",
                bottom: "-10%",
                right: "10%",
                width: "55%",
                height: "55%",
                borderRadius: "50%",
                background: "radial-gradient(circle, var(--accent-2-soft) 0%, transparent 70%)",
                filter: "blur(45px)",
                animation: "auroraShift2 30s ease-in-out infinite",
                willChange: "translate",
              }}
            />
          </div>
        )}

        {/* 2.2.2 Float DotField */}
        {variant !== "minimal" && (
          <div className="fx-layer" data-depth="0.15" style={{ position: "absolute", inset: 0 }}>
            <DotField />
          </div>
        )}
      </div>

      {/* 2.2.4 Hero SunBloom (Only login page / if sun is requested) */}
      {sun && (
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            opacity: 0.85,
            zIndex: 3,
          }}
        >
          <SunBloom size={360} />
        </div>
      )}
    </div>
  );
}
