import type { TerminalConnectionStatus, TerminalScope } from './types';

const ALLOWED_TRANSITIONS: Record<TerminalConnectionStatus, TerminalConnectionStatus[]> = {
  IDLE: ['LOADING', 'FATAL'],
  LOADING: ['CONNECTING', 'FATAL'],
  CONNECTING: ['CONNECTED', 'RECONNECTING', 'FATAL'],
  CONNECTED: ['RECONNECTING', 'IDLE', 'FATAL'],
  RECONNECTING: ['CONNECTING', 'CONNECTED', 'FATAL', 'IDLE'],
  FATAL: ['IDLE', 'LOADING'],
};

export class TerminalSessionState {
  private _status: TerminalConnectionStatus = 'IDLE';
  private _scope: TerminalScope | null = null;
  private readonly files = new Set<string>();

  get status(): TerminalConnectionStatus {
    return this._status;
  }

  get scope(): TerminalScope | null {
    return this._scope ? { ...this._scope } : null;
  }

  get knownFiles(): string[] {
    return [...this.files];
  }

  transition(next: TerminalConnectionStatus): void {
    if (!ALLOWED_TRANSITIONS[this._status].includes(next)) {
      throw new Error(`Illegal terminal transition: ${this._status} -> ${next}`);
    }
    this._status = next;
  }

  setScope(scope: TerminalScope): void {
    const scopeChanged = !this._scope
      || this._scope.backend !== scope.backend
      || this._scope.root !== scope.root
      || this._scope.project !== scope.project;
    this._scope = { ...scope };
    if (scopeChanged) this.files.clear();
  }

  rememberFile(path: string): void {
    const normalized = path.trim();
    if (normalized) this.files.add(normalized);
  }
}
