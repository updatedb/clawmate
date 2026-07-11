import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { TerminalOutputQueue } from './terminal-output-queue';
import { terminalOptions } from './terminal-runtime';
import { encodeInputFrame } from './terminal-transport';

export interface AgentInitOptions {
  backend: 'claude' | 'codex' | 'openclaw';
  wsUrl: string;
  rootId: string;
  dir: string;
  agentId?: string;
  domPrefix?: string;
  terminalV2?: boolean;
  scrollback?: number;
}

export class AgentPanelAdapter {
  private config: AgentInitOptions | null = null;
  private terminal: Terminal | null = null;
  private fit: FitAddon | null = null;
  private socket: WebSocket | null = null;
  private output: TerminalOutputQueue | null = null;
  private nextSequence = 1;

  init(config: AgentInitOptions): void { this.config = config; }

  open(rootId?: string, dir?: string): void {
    if (!this.config) return;
    if (rootId) this.config.rootId = rootId;
    if (dir !== undefined) this.config.dir = dir;
    const prefix = this.config.domPrefix === 'preview' ? 'preview' : '';
    const panel = document.getElementById(prefix ? 'previewAgentPanel' : 'agentPanel');
    const host = document.getElementById(prefix ? 'previewXtermContainer' : 'xtermContainer');
    if (!panel || !host || this.config.backend === 'openclaw') return;
    panel.classList.add('agent-panel-v2');
    panel.classList.remove('hidden');
    if (!this.terminal) {
      this.terminal = new Terminal(terminalOptions(this.config.scrollback || 10000));
      this.fit = new FitAddon();
      this.terminal.loadAddon(this.fit);
      this.terminal.open(host);
      this.fit.fit();
      this.output = new TerminalOutputQueue({
        write: (data, done) => this.terminal?.write(data, done),
        acknowledge: (sequence) => this.sendControl({ type: 'output_ack', sequence }),
        maxBytes: 4 * 1024 * 1024,
      });
      this.terminal.onData((data) => this.sendInput(new TextEncoder().encode(data)));
      this.terminal.onResize(({ cols, rows }) => this.sendControl({ type: 'resize', cols, rows }));
    }
    this.connect();
    this.terminal.focus();
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
    const panel = document.getElementById(this.config?.domPrefix === 'preview' ? 'previewAgentPanel' : 'agentPanel');
    panel?.classList.add('hidden');
  }

  isOpen(): boolean {
    const panel = document.getElementById(this.config?.domPrefix === 'preview' ? 'previewAgentPanel' : 'agentPanel');
    return !!panel && !panel.classList.contains('hidden');
  }

  focus(): void { this.terminal?.focus(); }
  updateRoot(rootId: string, dir?: string): void { if (this.config) { this.config.rootId = rootId; if (dir !== undefined) this.config.dir = dir; } }
  updateGrid(): void { this.fit?.fit(); }
  syncTheme(): void { this.terminal?.refresh(0, Math.max(0, (this.terminal.rows || 1) - 1)); }
  sendText(text: string): void { this.sendInput(new TextEncoder().encode(text)); }
  insertText(text: string): void { this.terminal?.input(text, true); }
  toggle(): void { this.isOpen() ? this.close() : this.open(); }

  private connect(): void {
    if (!this.config || this.socket?.readyState === WebSocket.OPEN) return;
    const ws = new WebSocket(`${this.config.wsUrl}/v2`);
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => this.sendControl({ type: 'hello', client_id: crypto.randomUUID(), root: this.config!.rootId, dir: this.config!.dir, backend: this.config!.backend, cols: this.terminal?.cols || 80, rows: this.terminal?.rows || 24 });
    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        const frame = new Uint8Array(event.data);
        const sequence = Number(new DataView(frame.buffer, frame.byteOffset, frame.byteLength).getBigUint64(0));
        this.output?.enqueue(sequence + frame.byteLength - 8, frame.slice(8));
      }
    };
    this.socket = ws;
  }

  private sendControl(message: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ v: 2, ...message }));
  }

  private sendInput(data: Uint8Array): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(encodeInputFrame(this.nextSequence++, data));
  }
}
