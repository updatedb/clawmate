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

export function terminalOptions(scrollback: number): ITerminalOptions {
  return {
    cursorBlink: true,
    convertEol: false,
    scrollback,
    minimumContrastRatio: 4.5,
    allowProposedApi: false,
    theme: terminalTheme(),
  };
}
