// A handful of thin-stroke (1.5 px) line icons, drawn here so the UI needs no icon dependency.
import type { ReactNode } from "react";

function Svg({ size = 16, children, label }: { size?: number; children: ReactNode; label?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden={label ? undefined : true} aria-label={label} role={label ? "img" : undefined}>
      {children}
    </svg>
  );
}
type P = { size?: number };
export const ArrowUp = (p: P) => <Svg {...p}><path d="M12 19V5" /><path d="m6 11 6-6 6 6" /></Svg>;
export const Chevron = (p: P) => <Svg {...p}><path d="m9 6 6 6-6 6" /></Svg>;
export const More = (p: P) => <Svg {...p}><circle cx="5.5" cy="12" r=".9" /><circle cx="12" cy="12" r=".9" /><circle cx="18.5" cy="12" r=".9" /></Svg>;
export const Close = (p: P) => <Svg {...p}><path d="M6 6l12 12M18 6 6 18" /></Svg>;
export const Plus = (p: P) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>;
export const Minus = (p: P) => <Svg {...p}><path d="M5 12h14" /></Svg>;
export const Layers = (p: P) => <Svg {...p}><path d="m12 4 8 4.5-8 4.5-8-4.5L12 4Z" /><path d="m4 13 8 4.5 8-4.5" /></Svg>;
export const Pin = (p: P) => <Svg {...p}><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11Z" /><circle cx="12" cy="10" r="2.2" /></Svg>;
export const Download = (p: P) => <Svg {...p}><path d="M12 4v11" /><path d="m7 10 5 5 5-5" /><path d="M5 20h14" /></Svg>;
export const Compose = (p: P) => <Svg {...p}><path d="M12 20h8" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4 11.5-11.5Z" /></Svg>;
