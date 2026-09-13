const shapes: Record<string, string> = {
  search: "M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
  model: "M12 5v4M5 15v-4h14v4M12 11v4M9 2h6v4H9zM2 16h6v5H2zM9 16h6v5H9zM16 16h6v5h-6z",
  book: "M12 5c-4-3-8-2-10-1v16c3-2 7-2 10 0 3-2 7-2 10 0V4c-3-1-7-2-10 1v15",
  flask: "M9 2h6M10 2v8L4 20q-1 2 2 2h12q3 0 2-2l-6-10V2M7 16h10",
  target: "M12 8v8M8 12h8M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  arrow: "M4 12h16M14 6l6 6-6 6",
  download: "M12 3v12M7 10l5 5 5-5M4 16v5h16v-5",
  fit: "M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5M8 8h8v8H8z",
  bolt: "M13 2L4 14h7l-1 8 10-13h-8l1-7",
  close: "M6 6l12 12M6 18L18 6",
  info: "M12 11v6M12 7v1M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0",
  plus: "M12 5v14M5 12h14",
  settings: "M3 6h18M3 12h18M3 18h18M8 3v6M16 9v6M8 15v6",
  check: "M4 12l5 5L20 6",
};
export function Icon({ name, size = 19 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={shapes[name] ?? shapes.model} /></svg>;
}
export function Logo() {
  return <svg width="36" height="40" viewBox="0 0 36 40" aria-hidden="true"><path d="M18 7v14L6 32m12-11 12 11" stroke="#217f84" strokeWidth="3" /><circle cx="18" cy="7" r="5" fill="#197d82" /><circle cx="18" cy="21" r="5" fill="#339fa0" /><circle cx="6" cy="32" r="5" fill="#197d82" /><circle cx="30" cy="32" r="5" fill="#197d82" /></svg>;
}
