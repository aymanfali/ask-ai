import type { SVGProps } from "react";

export type IconName =
  | "sparkles"
  | "plus"
  | "search"
  | "panel"
  | "chevron"
  | "message"
  | "more"
  | "edit"
  | "trash"
  | "copy"
  | "check"
  | "send"
  | "stop"
  | "menu"
  | "logout"
  | "user"
  | "code"
  | "file"
  | "globe"
  | "arrow"
  | "x"
  | "refresh"
  | "clock"
  | "shield"
  | "sun"
  | "moon";

const common: SVGProps<SVGSVGElement> = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
};

export function Icon({ name, size = 18, ...props }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  const base = { ...common, width: size, height: size, ...props };
  switch (name) {
    case "sparkles": return <svg {...base}><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7L12 3Z"/><path d="m19 16 .8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z"/><path d="m5 2 .6 1.4L7 4l-1.4.6L5 6l-.6-1.4L3 4l1.4-.6L5 2Z"/></svg>;
    case "plus": return <svg {...base}><path d="M12 5v14M5 12h14"/></svg>;
    case "search": return <svg {...base}><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 4.5 4.5"/></svg>;
    case "panel": return <svg {...base}><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg>;
    case "chevron": return <svg {...base}><path d="m9 18 6-6-6-6"/></svg>;
    case "message": return <svg {...base}><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-6.5A7.5 7.5 0 1 1 20 11.5Z"/></svg>;
    case "more": return <svg {...base}><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>;
    case "edit": return <svg {...base}><path d="m14 5 5 5M4 20l4.2-.8L19 8.4 15.6 5 4.8 15.8 4 20Z"/></svg>;
    case "trash": return <svg {...base}><path d="M4 7h16M10 11v6m4-6v6M6 7l1 14h10l1-14M9 7V4h6v3"/></svg>;
    case "copy": return <svg {...base}><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>;
    case "check": return <svg {...base}><path d="m5 12 4 4L19 6"/></svg>;
    case "send": return <svg {...base}><path d="m21 3-7.5 18-3.3-7.2L3 10.5 21 3Z"/><path d="M10.2 13.8 15 9"/></svg>;
    case "stop": return <svg {...base}><rect x="5" y="5" width="14" height="14" rx="2"/></svg>;
    case "menu": return <svg {...base}><path d="M4 7h16M4 12h16M4 17h16"/></svg>;
    case "logout": return <svg {...base}><path d="M10 17l5-5-5-5M15 12H3"/><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/></svg>;
    case "user": return <svg {...base}><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>;
    case "code": return <svg {...base}><path d="m8 8-4 4 4 4m8-8 4 4-4 4m-3-11-2 14"/></svg>;
    case "file": return <svg {...base}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h8"/></svg>;
    case "globe": return <svg {...base}><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>;
    case "arrow": return <svg {...base}><path d="M5 12h14m-6-6 6 6-6 6"/></svg>;
    case "x": return <svg {...base}><path d="m6 6 12 12M18 6 6 18"/></svg>;
    case "refresh": return <svg {...base}><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.6 9a7 7 0 0 1 11.8-2L20 12M4 12l2.6 5a7 7 0 0 0 11.8-2"/></svg>;
    case "clock": return <svg {...base}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>;
    case "shield": return <svg {...base}><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></svg>;
    case "sun": return <svg {...base}><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>;
    case "moon": return <svg {...base}><path d="M20.5 14A8.5 8.5 0 0 1 10 3.5 8.5 8.5 0 1 0 20.5 14Z"/></svg>;
  }
  return null;
}
