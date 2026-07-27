import type { ITheme, ITerminalOptions } from '@xterm/xterm';

export function terminalTheme(): ITheme {
  if (typeof document === 'undefined') {
    return {
      background: '#f8fafc', foreground: '#0f172a', cursor: '#0d9488',
      cursorAccent: '#f8fafc', selectionBackground: '#f0fdfa',
      selectionForeground: '#0f172a', selectionInactiveBackground: '#e2e8f0',
    };
  }
  const style = getComputedStyle(document.documentElement);
  const tok = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    background: tok('--bg-code', '#f8fafc'),
    foreground: tok('--text-primary', '#0f172a'),
    cursor: tok('--accent', '#0d9488'),
    cursorAccent: tok('--bg-code', '#f8fafc'),
    selectionBackground: tok('--accent-light', '#f0fdfa'),
    selectionForeground: tok('--text-primary', '#0f172a'),
    selectionInactiveBackground: tok('--border-color', '#e2e8f0'),
  };
}

/** Default monospace font stack — must match the --font-mono CSS custom property
 *  in tokens.css so that xterm's internal CharSizeService measurement and the
 *  canvas‑based measureCellWidth use the same font. */
const DEFAULT_MONO_FONT = '"JetBrains Mono", "Fira Code", "Cascadia Code", Consolas, monospace';

/**
 * Resolve the monospace font family from the --font-mono CSS custom property,
 * falling back to the hard‑coded DEFAULT_MONO_FONT when unavailable.
 */
function resolveFontFamily(): string {
  if (typeof document === 'undefined') return DEFAULT_MONO_FONT;
  const style = getComputedStyle(document.documentElement);
  return style.getPropertyValue('--font-mono').trim() || DEFAULT_MONO_FONT;
}

export function terminalOptions(scrollback: number): ITerminalOptions {
  return {
    cursorBlink: true,
    convertEol: false,
    scrollback,
    minimumContrastRatio: 4.5,
    allowProposedApi: false,
    fontFamily: resolveFontFamily(),
    theme: terminalTheme(),
    overviewRuler: { width: 6 },
  };
}
