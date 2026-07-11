import type { ITerminalOptions } from '@xterm/xterm';

export function terminalOptions(scrollback: number): ITerminalOptions {
  return {
    cursorBlink: true,
    convertEol: false,
    scrollback,
    minimumContrastRatio: 4.5,
    allowProposedApi: false,
  };
}
