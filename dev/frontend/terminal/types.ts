export type TerminalConnectionStatus =
  | 'IDLE'
  | 'LOADING'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'RECONNECTING'
  | 'FATAL';

export interface TerminalScope {
  backend: 'claude' | 'codex';
  root: string;
  project: string;
}
