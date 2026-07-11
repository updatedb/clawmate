import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { SearchAddon } from '@xterm/addon-search';
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

export function syncMainAgentPanelLayout(open: boolean): void {
  const content = document.querySelector<HTMLElement>('.content');
  if (!content || window.innerWidth < 768) {
    document.body.classList.toggle('agent-open', open);
    return;
  }
  const sidebar = document.getElementById('sidebar');
  const sidebarHidden = sidebar && (
    sidebar.classList.contains('hidden') || getComputedStyle(sidebar).display === 'none'
  );
  const sidebarWidth = sidebarHidden ? '0px' : '240px';
  const panelRatio = window.innerWidth <= 1024 ? 0.6 : 0.46;
  const panelWidth = Math.min(820, Math.max(420, window.innerWidth * panelRatio));
  const panelTrack = `minmax(420px, ${panelWidth}px)`;
  content.style.gridTemplateColumns = open
    ? `${sidebarWidth} 1fr 5px ${panelTrack}`
    : `${sidebarWidth} 1fr 0px 0px`;
  document.body.classList.toggle('agent-open', open);
}

export class AgentPanelAdapter {
  private config: AgentInitOptions | null = null;
  private terminal: Terminal | null = null;
  private fit: FitAddon | null = null;
  private search: SearchAddon | null = null;
  private socket: WebSocket | null = null;
  private output: TerminalOutputQueue | null = null;
  private nextSequence = 1;

  init(config: AgentInitOptions): void { this.config = config; }

  setBackend(backend: AgentInitOptions['backend']): void {
    if (!this.config || this.config.backend === backend) return;
    this.config.backend = backend;
    this.socket?.close();
    this.socket = null;
    this.disposeTerminal();
    this.setStatus('未连接');
    if (backend === 'openclaw') {
      const panel = document.getElementById(this.config.domPrefix === 'preview' ? 'previewAgentPanel' : 'agentPanel');
      panel?.classList.remove('agent-panel-v2');
      this.close();
      return;
    }
    if (this.isOpen()) this.open();
  }

  open(rootId?: string, dir?: string): void {
    if (!this.config) return;
    if (rootId) this.config.rootId = rootId;
    if (dir !== undefined) this.config.dir = dir;
    const prefix = this.config.domPrefix === 'preview' ? 'preview' : '';
    const panel = document.getElementById(prefix ? 'previewAgentPanel' : 'agentPanel');
    const host = document.getElementById(prefix ? 'previewXtermContainer' : 'xtermContainer');
    const chat = document.getElementById(prefix ? 'previewAgentChatView' : 'agentChatView');
    if (!panel || !host || this.config.backend === 'openclaw') return;
    panel.classList.add('agent-panel-v2');
    panel.classList.remove('hidden');
    host.classList.remove('hidden');
    chat?.classList.add('hidden');
    if (!prefix) syncMainAgentPanelLayout(true);
    this.bindToolbar(prefix);
    if (!this.terminal) {
      this.terminal = new Terminal(terminalOptions(this.config.scrollback || 10000));
      this.fit = new FitAddon();
      this.search = new SearchAddon();
      this.terminal.loadAddon(this.fit);
      this.terminal.loadAddon(this.search);
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
    if (this.config?.domPrefix !== 'preview') syncMainAgentPanelLayout(false);
    this.setStatus('未连接');
  }

  isOpen(): boolean {
    const panel = document.getElementById(this.config?.domPrefix === 'preview' ? 'previewAgentPanel' : 'agentPanel');
    return !!panel && !panel.classList.contains('hidden');
  }

  focus(): void { this.terminal?.focus(); }
  updateRoot(rootId: string, dir?: string): void { if (this.config) { this.config.rootId = rootId; if (dir !== undefined) this.config.dir = dir; } }
  updateGrid(): void {
    if (this.config?.domPrefix !== 'preview') {
      syncMainAgentPanelLayout(this.isOpen());
    }
    this.fit?.fit();
  }
  syncTheme(): void { this.terminal?.refresh(0, Math.max(0, (this.terminal.rows || 1) - 1)); }
  sendText(text: string): void { this.sendInput(new TextEncoder().encode(text)); }
  insertText(text: string): void { this.terminal?.input(text, true); }
  toggle(): void { this.isOpen() ? this.close() : this.open(); }

  private connect(): void {
    if (!this.config || this.socket?.readyState === WebSocket.OPEN) return;
    this.setStatus('连接中');
    const ws = new WebSocket(`${this.config.wsUrl}/v2`);
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => {
      this.setStatus('已连接');
      this.sendControl({ type: 'hello', client_id: crypto.randomUUID(), root: this.config!.rootId, dir: this.config!.dir, backend: this.config!.backend, cols: this.terminal?.cols || 80, rows: this.terminal?.rows || 24 });
    };
    ws.onerror = () => this.setStatus('连接错误');
    ws.onclose = () => { if (this.socket === ws) this.setStatus('已断开'); };
    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        const frame = new Uint8Array(event.data);
        const sequence = Number(new DataView(frame.buffer, frame.byteOffset, frame.byteLength).getBigUint64(0));
        this.output?.enqueue(sequence + frame.byteLength - 8, frame.slice(8));
      }
    };
    this.socket = ws;
  }

  private bindToolbar(prefix: string): void {
    const id = (name: string) => `${prefix}${name}`;
    const searchRow = document.getElementById(id('AgentSearchRow')) as HTMLElement | null;
    const searchInput = document.getElementById(id('AgentSearchInput')) as HTMLInputElement | null;
    const searchButton = document.getElementById(id('AgentSearch'));
    const searchPrev = document.getElementById(id('AgentSearchPrev'));
    const searchNext = document.getElementById(id('AgentSearchNext'));
    const runSearch = (forward: boolean) => {
      const value = searchInput?.value.trim();
      if (!value || !this.search) return;
      forward ? this.search.findNext(value) : this.search.findPrevious(value);
    };
    if (searchButton) searchButton.onclick = () => {
      if (searchRow) searchRow.hidden = !searchRow.hidden;
      if (!searchRow?.hidden) searchInput?.focus();
    };
    if (searchInput) searchInput.oninput = () => runSearch(true);
    if (searchPrev) searchPrev.onclick = () => runSearch(false);
    if (searchNext) searchNext.onclick = () => runSearch(true);
    const clear = document.getElementById(id('AgentClear'));
    if (clear) clear.onclick = () => this.terminal?.clear();
    const copy = document.getElementById(id('AgentCopy'));
    if (copy) copy.onclick = () => {
      const text = this.terminal?.getSelection() || '';
      if (text && navigator.clipboard) void navigator.clipboard.writeText(text);
    };
    const adjustFont = (delta: number) => {
      if (!this.terminal) return;
      this.terminal.options.fontSize = Math.max(10, Math.min(22, (this.terminal.options.fontSize || 14) + delta));
      this.fit?.fit();
    };
    const fontDown = document.getElementById(id('AgentFontDown'));
    if (fontDown) fontDown.onclick = () => adjustFont(-1);
    const fontUp = document.getElementById(id('AgentFontUp'));
    if (fontUp) fontUp.onclick = () => adjustFont(1);
    const reconnect = document.getElementById(id('AgentReconnect'));
    if (reconnect) reconnect.onclick = () => {
      this.socket?.close(); this.socket = null; this.connect();
    };
  }

  private setStatus(text: string): void {
    const prefix = this.config?.domPrefix === 'preview' ? 'preview' : '';
    const status = document.getElementById(`${prefix}AgentStatus`);
    if (status) status.textContent = text;
  }

  private disposeTerminal(): void {
    this.terminal?.dispose();
    this.terminal = null;
    this.fit = null;
    this.search = null;
    this.output = null;
    const prefix = this.config?.domPrefix === 'preview' ? 'preview' : '';
    const host = document.getElementById(prefix ? 'previewXtermContainer' : 'xtermContainer');
    if (host) host.innerHTML = '';
  }

  private sendControl(message: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ v: 2, ...message }));
  }

  private sendInput(data: Uint8Array): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(encodeInputFrame(this.nextSequence++, data));
  }
}
