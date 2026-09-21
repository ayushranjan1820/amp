/**
 * Apply primary palette from agents catalog metadata (admin-configured in MongoDB).
 * Overrides @theme defaults in index.css at runtime via CSS variables on :root.
 */
const HEX = /^#[0-9A-Fa-f]{3,8}$/;

export function applyPrimaryColorsFromCatalog(
  primaryColors: Record<string, string> | null | undefined,
): void {
  if (!primaryColors || typeof primaryColors !== 'object') return;
  const root = document.documentElement;
  for (const [step, raw] of Object.entries(primaryColors)) {
    if (!/^\d+$/.test(step)) continue;
    const hex = String(raw ?? '').trim();
    if (!HEX.test(hex)) continue;
    root.style.setProperty(`--color-primary-${step}`, hex);
  }
}
