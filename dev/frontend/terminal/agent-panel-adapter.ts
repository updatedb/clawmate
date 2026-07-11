import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { SearchAddon } from '@xterm/addon-search';
import { TerminalOutputQueue } from './terminal-output-queue';
import { terminalOptions, terminalTheme } from './terminal-runtime';
import { encodeInputFrame } from './terminal-transport';
import { DEFAULT_RETRY, OpenClawTransport, type OpenClawMessage } from './openclaw-transport';
import { formatHistoryDateLabel, formatHistoryRowMeta, formatSessionDateTime, groupHistorySessions, type HistorySession } from './session-history-panel';

export interface AgentInitOptions {
  backend: 'claude' | 'codex' | 'openclaw';
  wsUrl: string;
  rootId: string;
  dir: string;
  project?: string;
  agentId?: string;
  domPrefix?: string;
  scrollback?: number;
}

export interface AgentFileContext {
  path?: string;
}

const AGENT_BACKEND_PREFERENCES_STORAGE_KEY = 'clawmate.agent.backend-preferences.v1';
const VALID_AGENT_BACKENDS: readonly AgentInitOptions['backend'][] = ['claude', 'codex', 'openclaw'];

function isAgentBackend(value: unknown): value is AgentInitOptions['backend'] {
  return typeof value === 'string' && VALID_AGENT_BACKENDS.includes(value as AgentInitOptions['backend']);
}

function agentProjectScope(dir: string, project?: string): string {
  return project || dir.split('/').filter(Boolean)[0] || 'root';
}

export function formatAgentScope(backend: AgentInitOptions['backend'], rootId: string, dir: string): string {
  const project = dir.split('/').filter(Boolean)[0] || 'root';
  return `${backend}:${rootId || 'root'}:${project}`;
}

const MIN_READABLE_TERMINAL_COLUMNS = 84;
const MAX_TERMINAL_FONT_SIZE = 20;

/**
 * xterm reserves this many CSS pixels for the vertical scrollbar track
 * (DEFAULT_SCROLL_BAR_WIDTH = 14) when scrollback > 0.  The scrollbar is
 * positioned as an overlay so the space isn't visible, but FitAddon still
 * subtracts it from the available width when computing columns.
 */
const XTERM_SCROLLBAR_WIDTH = 14;

/**
 * Flat CSS‑pixel margin added to the computed canvas width so that xterm's
 * FitAddon (which uses floor‑division) always produces at least
 * MIN_READABLE_TERMINAL_COLUMNS columns.  This small flat amount absorbs:
 *
 *  1. Sub‑pixel rounding differences between canvas measureText and xterm's
 *     DOM‑based character‑width measurement (offsetWidth / 32).
 *  2. Font‑hinting boundary effects across platforms and font sizes.
 *
 * Unlike a per‑cell margin (which scales linearly with columns), a flat
 * safety margin is small enough that it doesn't materially over‑estimate
 * the required panel width at practical column counts.
 */
const FLAT_SAFETY_MARGIN = 8;

/** Cache for canvas‑measured cell widths, keyed by fontSize (10–20). */
const _cellWidthCache = new Map<number, number>();

/**
 * Resolve the monospace font family string used by the terminal.
 * Reads the --font-mono CSS custom property, falling back to the
 * xterm font stack so the canvas measurement matches xterm's own.
 */
function _resolveMonoFontFamily(): string {
  if (typeof document === 'undefined') return '"JetBrains Mono", "Fira Code", "Cascadia Code", Consolas, monospace';
  const style = getComputedStyle(document.documentElement);
  return style.getPropertyValue('--font-mono').trim() || '"JetBrains Mono", "Fira Code", "Cascadia Code", Consolas, monospace';
}

/**
 * Measure the actual pixel width of a monospace character cell for the
 * terminal's loaded font at the given size, using an OffscreenCanvas.
 *
 * Returns 0 when measurement is unavailable (test environments, SSR).
 */
export function measureCellWidth(fontSize: number): number {
  const cached = _cellWidthCache.get(fontSize);
  if (cached !== undefined) return cached;
  if (typeof document === 'undefined') return 0;
  const fontFamily = _resolveMonoFontFamily();
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 100;
    canvas.height = 100;
    const ctx = canvas.getContext('2d');
    if (!ctx) return 0;
    ctx.font = `${fontSize}px ${fontFamily}`;
    const width = ctx.measureText('W').width;
    if (Number.isFinite(width) && width > 0) {
      _cellWidthCache.set(fontSize, width);
      return width;
    }
  } catch {
    /* canvas unavailable */
  }
  return 0;
}

/**
 * Compute the minimum panel width that guarantees `MIN_READABLE_TERMINAL_COLUMNS`
 * columns in xterm at the given font size.
 *
 * The calculation mirrors xterm's own dimension math to avoid over‑estimation:
 *
 *  1. Measure the character width (canvas measureText).
 *  2. xterm's final `css.cell.width` is derived from the total canvas width
 *     rounded to the nearest integer CSS pixel:
 *       `css.cell.width = Math.round(charWidth × cols) / cols`
 *  3. FitAddon computes available columns with floor‑division:
 *       `cols = ⌊(parentWidth − padding − scrollbar) / css.cell.width⌋`
 *
 * So the exact CSS‑pixel canvas width that yields N columns is
 * `Math.round(charWidth × N)`.  Adding the scrollbar reservation and a flat
 * safety margin gives the panel‑width lower bound.
 */
export function getAgentPanelWidthBounds(fontSize = 14): { min: number; max: number } {
  const nonTerminal = XTERM_SCROLLBAR_WIDTH + FLAT_SAFETY_MARGIN;

  const measured = measureCellWidth(fontSize);
  const readableCanvas = measured > 0
    ? Math.round(measured * MIN_READABLE_TERMINAL_COLUMNS)
    : Math.round(fontSize * 0.625 * MIN_READABLE_TERMINAL_COLUMNS);
  const readableMin = readableCanvas + nonTerminal;
  const min = Math.max(420, readableMin);

  // The max bound is computed at MAX_TERMINAL_FONT_SIZE so it represents the
  // largest sensible panel width regardless of the current font size.
  const maxMeasured = measureCellWidth(MAX_TERMINAL_FONT_SIZE);
  const maxCanvas = maxMeasured > 0
    ? Math.round(maxMeasured * MIN_READABLE_TERMINAL_COLUMNS)
    : Math.round(MAX_TERMINAL_FONT_SIZE * 0.625 * MIN_READABLE_TERMINAL_COLUMNS);
  const maxReadable = maxCanvas + nonTerminal;
  const sidebar = document.getElementById('sidebar');
  const sidebarWidth = sidebar && !sidebar.classList.contains('hidden') && getComputedStyle(sidebar).display !== 'none' ? 240 : 0;
  const availableMax = window.innerWidth - sidebarWidth - 315 - 5;
  return { min, max: Math.max(min, Math.min(maxReadable, availableMax)) };
}

/**
 * Scale the panel width proportionally when the font size changes.
 * The result is only a starting point — the caller (setPanelWidth) clamps it to
 * the actual readable bounds so transient rounding errors are absorbed.
 */
export function scaleAgentPanelWidth(width: number, oldFontSize: number, newFontSize: number): number {
  if (!Number.isFinite(width) || oldFontSize <= 0 || newFontSize <= 0) return width;
  return Math.round(width * (newFontSize / oldFontSize));
}

/**
 * Derive the largest font size (10–20) whose readable minimum panel width fits
 * within the given `width`.  Uses binary search against `getAgentPanelWidthBounds`
 * so the result is consistent with how panel width → font size mapping actually
 * behaves, including measured cell widths and safety margins.
 */
export function getFontSizeForAgentPanelWidth(width: number): number {
  if (!Number.isFinite(width) || width <= XTERM_SCROLLBAR_WIDTH + FLAT_SAFETY_MARGIN) return 10;
  let lo = 10;
  let hi = MAX_TERMINAL_FONT_SIZE;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    const bounds = getAgentPanelWidthBounds(mid);
    if (bounds.min <= width) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

export function syncMainAgentPanelLayout(open: boolean, panelWidth?: number): void {
  document.body.classList.toggle('agent-open', open);
  const content = document.querySelector<HTMLElement>('.content');
  if (!content || window.innerWidth < 768) {
    return;
  }
  const sidebar = document.getElementById('sidebar');
  const sidebarHidden = sidebar && (
    sidebar.classList.contains('hidden') || getComputedStyle(sidebar).display === 'none'
  );
  const sidebarWidth = sidebarHidden ? '0px' : '240px';
  const panelRatio = window.innerWidth <= 1024 ? 0.6 : 0.46;
  const defaultWidth = Math.min(820, Math.max(420, window.innerWidth * panelRatio));
  const panelTrack = `minmax(420px, ${(panelWidth || defaultWidth)}px)`;
  content.style.gridTemplateColumns = open
    ? `${sidebarWidth} 1fr 5px ${panelTrack}`
    : `${sidebarWidth} 1fr 0px 0px`;
}

/** Lazily-built markdown-it instance, shared across all render calls. */
let _cachedMd: any = null;

function _getMarkdownit(): any {
  const runtime = window as Window & Record<string, any>;
  if (typeof runtime.markdownit !== 'function') return null;
  if (_cachedMd) return _cachedMd;
  const md = runtime.markdownit({
    html: false,
    linkify: true,
    typographer: true,
    breaks: true,
  });
  if (typeof runtime.markdownitEmoji === 'function') md.use(runtime.markdownitEmoji);
  if (typeof runtime.markdownitFootnote === 'function') md.use(runtime.markdownitFootnote);
  if (typeof runtime.markdownitTaskLists === 'function') {
    md.use(runtime.markdownitTaskLists, { enabled: true, label: true, labelAfter: true });
  }
  _cachedMd = md;
  return md;
}

/** Render gateway text with the same Markdown runtime used by the file preview. */
export function renderOpenClawMarkdown(text: string): string | null {
  const md = _getMarkdownit();
  if (!md) return null;
  const runtime = window as Window & Record<string, any>;
  const html = md.render(text);
  return typeof runtime.DOMPurify?.sanitize === 'function'
    ? runtime.DOMPurify.sanitize(html, { ADD_ATTR: ['class', 'target', 'rel'] })
    : html;
}

export class AgentPanelAdapter {
  private config: AgentInitOptions | null = null;
  private terminal: Terminal | null = null;
  private fit: FitAddon | null = null;
  private search: SearchAddon | null = null;
  private socket: WebSocket | null = null;
  private readonly openclaw = new OpenClawTransport();
  private output: TerminalOutputQueue | null = null;
  private nextSequence = 1;
  private openclawInfo: HTMLElement | null = null;
  private openclawAssistant: HTMLElement | null = null;
  private openclawSessionId = '';
  private pendingFileContext = '';
  private contextGeneration = 0;
  private panelWidth = this.readPanelWidth();
  private resizeObserver: ResizeObserver | null = null;
  private historyQuery = '';
  private historyBackend = '';
  private historyOffset = 0;
  private historyDates: string[] = [];
  private historySelectedDateIndex = 0;
  private historyAxisScrollIndex = 0;
  private readonly historyLimit = 15;
  private historyRequest = 0;
  private wsRetryCount = 0;
  private wsRetryTimer: ReturnType<typeof setTimeout> | null = null;
  private wsClosedByUser = false;
  private defaultBackend: AgentInitOptions['backend'] = 'claude';
  private pendingFreshSession: (() => void) | null = null;
  private readonly wsMaxRetries = DEFAULT_RETRY.maxRetries;
  private readonly wsRetryBaseDelay = DEFAULT_RETRY.baseDelay;
  private readonly wsRetryMaxDelay = DEFAULT_RETRY.maxDelay;

  /** Highest output sequence acknowledged by the backend.  Sent on reconnect so
   *  the session can skip replaying already‑delivered data. */
  private lastOutputAck = 0;

  /** OpenClaw chat message buffer — accumulates every message so we can
   *  replays across project‑switch reconnect cycles. */
  private readonly _openClawMessages: OpenClawMessage[] = [];
  /** Per‑scope cache of saved OpenClaw chat messages, keyed by backend:rootId:project. */
  private readonly _savedOpenClawMessages = new Map<string, OpenClawMessage[]>();

  /** Application‑layer heartbeat timer (every 25 s) to keep intermediate
   *  proxies from closing the WebSocket during idle phases. */
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;

  init(config: AgentInitOptions): void {
    const previousConfig = this.config;
    const previousScope = previousConfig ? this._scopeKey(previousConfig.rootId, previousConfig.dir, previousConfig.project) : '';
    const nextScope = this._scopeKey(config.rootId, config.dir, config.project);
    const prefix = config.domPrefix === 'preview' ? 'preview' : '';
    const reopenAfterScopeChange = !!previousConfig && previousScope !== nextScope && this.isOpen();
    if (reopenAfterScopeChange) {
      this.resetScopeState(prefix, this._openClawScopeKey());
    }
    this.config = { ...config };
    this.defaultBackend = config.backend;
    this.config.backend = this.readBackendPreference(nextScope, config.backend);
    this.updateTitle();
    this.bindResizeHandle(prefix);
    const select = document.getElementById(prefix ? 'previewAgentBackendSelect' : 'agentBackendSelect') as HTMLSelectElement | null;
    if (select) {
      select.value = this.config.backend;
      select.onchange = () => this.setBackend(select.value as AgentInitOptions['backend']);
    }
    const close = document.getElementById(prefix ? 'previewBtnCloseAgent' : 'btnCloseAgent');
    if (close) close.onclick = () => this.close();
    const fresh = document.getElementById(prefix ? 'previewBtnNewAgentSession' : 'btnNewAgentSession');
    if (fresh) fresh.onclick = () => this.startFreshSession();
    const history = document.getElementById(prefix ? 'previewBtnAgentHistory' : 'btnAgentHistory');
    if (history) history.onclick = () => this.toggleHistory(prefix);
    if (reopenAfterScopeChange) this.open();
  }

  setBackend(backend: AgentInitOptions['backend']): void {
    if (!this.config || this.config.backend === backend) return;
    const wasOpen = this.isOpen();
    const prefix = this.config.domPrefix === 'preview' ? 'preview' : '';
    const oldScopeKey = this._openClawScopeKey();
    const historyOverlay = document.getElementById(prefix ? 'previewAgentHistoryOverlay' : 'agentHistoryOverlay');
    const historyWasOpen = !!historyOverlay && !historyOverlay.classList.contains('hidden');
    this.saveBackendPreference(this._scopeKey(this.config.rootId, this.config.dir, this.config.project), backend);
    this.clearOpenClawMessages(prefix, oldScopeKey);
    this.openclaw.close();
    this.config.backend = backend;
    this.updateTitle();
    this.wsClosedByUser = true;
    this.clearWsRetryTimer();
    this.socket?.close();
    this.socket = null;
    this.disposeTerminal();
    this.setStatus('未连接');
    // Reset ack so the server replays buffered output from the ReplayRing
    // on the new backend's session.
    this.lastOutputAck = 0;
    if (wasOpen) this.open();
    if (historyWasOpen && historyOverlay) this.loadHistory(historyOverlay, true);
  }

  open(rootId?: string, dir?: string, fileContext?: AgentFileContext): void {
    if (!this.config) return;
    if (rootId) this.config.rootId = rootId;
    if (dir !== undefined) this.config.dir = dir;
    this.updateTitle();
    const prefix = this.config.domPrefix === 'preview' ? 'preview' : '';
    const select = document.getElementById(prefix ? 'previewAgentBackendSelect' : 'agentBackendSelect') as HTMLSelectElement | null;
    if (select) select.value = this.config.backend;
    const panel = document.getElementById(prefix ? 'previewAgentPanel' : 'agentPanel');
    const host = document.getElementById(prefix ? 'previewXtermContainer' : 'xtermContainer');
    const chat = document.getElementById(prefix ? 'previewAgentChatView' : 'agentChatView');
    if (!panel || !host || !chat) return;
    document.getElementById(prefix ? 'previewResizeHandle' : 'agentResizeHandle')?.classList.remove('hidden');
    if (this.config.backend === 'openclaw') {
      panel.classList.remove('agent-panel-v2', 'hidden');
      if (!prefix) syncMainAgentPanelLayout(true, this.panelWidth);
      this.setTerminalToolbarVisible(prefix, false);
      host.classList.add('hidden');
      chat.classList.remove('hidden');
      this.bindChat(prefix);
      this.openclaw.connect(
        { wsUrl: this.config.wsUrl, rootId: this.config.rootId, dir: this.config.dir, agentId: this.config.agentId || '', sessionId: this.openclawSessionId },
        (message) => this.handleOpenClawMessage(message, prefix),
        (status) => this.setStatus(status === 'connected' ? '已连接' : status === 'connecting' ? '连接中' : '连接断开'),
      );
      // Restore cached OpenClaw messages for this scope so that switching
      // back to a project shows the previous session's content.
      const savedKey = this._openClawScopeKey();
      const saved = this._savedOpenClawMessages.get(savedKey);
      if (saved?.length) {
        for (const msg of saved) this.handleOpenClawMessage(msg, prefix);
      }
    } else {
      panel.classList.add('agent-panel-v2');
      panel.classList.remove('hidden');
      this.setTerminalToolbarVisible(prefix, true);
      host.classList.remove('hidden');
      chat?.classList.add('hidden');
      if (!prefix) syncMainAgentPanelLayout(true, this.panelWidth);
      this.bindToolbar(prefix);
      if (!this.terminal) {
        this.terminal = new Terminal(terminalOptions(this.config.scrollback || 10000));
        this.fit = new FitAddon();
        this.search = new SearchAddon();
        this.terminal.loadAddon(this.fit);
        this.terminal.loadAddon(this.search);
        this.terminal.open(host);
        // Restore the saved geometry first; then derive the matching font from
        // that geometry instead of expanding it back to the default-font floor.
        this.setPanelWidth(this.panelWidth, false);
        this.syncFontToPanelWidth();
        this.observeTerminalHost(host);
        this.scheduleTerminalFit(host);
        this.output = new TerminalOutputQueue({
          write: (data, done) => this.terminal?.write(data, done),
          acknowledge: (sequence) => {
            this.lastOutputAck = Math.max(this.lastOutputAck, sequence);
            this.sendControl({ type: 'output_ack', sequence });
          },
          maxBytes: 4 * 1024 * 1024,
        });
        this.terminal.onData((data) => this.sendInput(new TextEncoder().encode(data)));
        this.terminal.onResize(({ cols, rows }) => this.sendControl({ type: 'resize', cols, rows }));
      }
      this.connect();
    }
    this.injectFileContext(fileContext, prefix);
    this.terminal?.focus();
  }

  close(): void {
    // 仅关闭 WebSocket，不发送 terminate。session 在服务端保持存活以便重新打开时恢复连续性。
    this.openclaw.close();
    this.wsClosedByUser = true;
    this.stopHeartbeat();
    this.clearWsRetryTimer();
    this.socket?.close();
    this.socket = null;
    const panel = document.getElementById(this.config?.domPrefix === 'preview' ? 'previewAgentPanel' : 'agentPanel');
    const toggle = document.getElementById('btnToggleAgent');
    document.getElementById(this.config?.domPrefix === 'preview' ? 'previewResizeHandle' : 'agentResizeHandle')?.classList.add('hidden');
    panel?.classList.add('hidden');
    if (toggle && this.config?.domPrefix !== 'preview') toggle.classList.remove('active');
    if (this.config?.domPrefix !== 'preview') syncMainAgentPanelLayout(false);
    this.setStatus('未连接');
  }

  isOpen(): boolean {
    const panel = document.getElementById(this.config?.domPrefix === 'preview' ? 'previewAgentPanel' : 'agentPanel');
    return !!panel && !panel.classList.contains('hidden');
  }

  focus(): void { this.terminal?.focus(); }
  updateRoot(rootId: string, dir?: string, project?: string): void {
    if (!this.config) return;
    const nextDir = dir === undefined ? this.config.dir : dir;
    const nextProject = project === undefined ? this.config.project : project;
    const rootChanged = this.config.rootId !== rootId;
    const projectChanged = this.config.project !== nextProject;
    if (!rootChanged && !projectChanged) return;
    // Save the old scope key BEFORE updating config, so clearOpenClawMessages
    // caches messages under the correct (old) scope key.
    const prefix = this.config.domPrefix === 'preview' ? 'preview' : '';
    const oldScopeKey = this._openClawScopeKey();
    const nextScope = this._scopeKey(rootId, nextDir, nextProject);
    const nextBackend = this.readBackendPreference(nextScope, this.defaultBackend);
    this.config.rootId = rootId;
    this.config.dir = nextDir;
    this.config.project = nextProject;
    this.config.backend = nextBackend;
    this.updateTitle();
    // root 或 project 变了 → 无论 panel 当前是否打开，都必须清理旧
    // terminal/socket/ack 状态。否则 panel 关闭时切换 scope，重新打开
    // 会复用旧 terminal buffer，把旧 backend/session 的内容带到新 scope。
    const needsReconnect = rootChanged || projectChanged;
    if (needsReconnect) {
      const historyOverlay = document.getElementById(prefix ? 'previewAgentHistoryOverlay' : 'agentHistoryOverlay');
      const historyWasOpen = !!historyOverlay && !historyOverlay.classList.contains('hidden');
      this.resetScopeState(prefix, oldScopeKey);
      if (!this.isOpen()) return;
      // Reset ack so the server replays all buffered output from the ReplayRing,
      // restoring the previous session's content in the new terminal instance.
      this.open();
      if (historyWasOpen && historyOverlay) this.loadHistory(historyOverlay, true);
    }
  }
  updateGrid(): void {
    if (this.config?.domPrefix !== 'preview') {
      syncMainAgentPanelLayout(this.isOpen(), this.panelWidth);
    } else {
      this.applyPreviewPanelWidth();
    }
    this.scheduleTerminalFit();
  }
  syncTheme(): void {
    if (!this.terminal) return;
    this.terminal.options.theme = terminalTheme();
    this.terminal.refresh(0, Math.max(0, (this.terminal.rows || 1) - 1));
  }
  sendText(text: string): void {
    if (this.config?.backend === 'openclaw') this.openclaw.sendText(text);
    else this.sendInput(new TextEncoder().encode(text));
  }
  insertText(text: string): void { this.terminal?.input(text, true); }
  toggle(): void { this.isOpen() ? this.close() : this.open(); }

  private connect(): void {
    if (!this.config || this.socket?.readyState === WebSocket.OPEN) return;
    this.wsClosedByUser = false;
    this.setStatus('连接中');
    const ws = new WebSocket(`${this.config.wsUrl}/v2`);
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => {
      this.wsRetryCount = 0;
      this.setStatus('连接中');
      this.startHeartbeat();
      this.sendControl({ type: 'hello', client_id: crypto.randomUUID(), root: this.config!.rootId, dir: this.config!.dir, backend: this.config!.backend, cols: this.terminal?.cols || 80, rows: this.terminal?.rows || 24, last_output_ack: this.lastOutputAck });
      if (this.pendingFileContext) {
        const context = this.pendingFileContext;
        this.pendingFileContext = '';
        this.sendInput(new TextEncoder().encode(context));
      }
    };
    ws.onerror = () => { /* onclose will fire next */ };
    ws.onclose = (event) => {
      if (this.socket !== ws) return;
      this.socket = null;
      this.stopHeartbeat();
      const freshSession = this.pendingFreshSession;
      this.pendingFreshSession = null;
      if (freshSession) {
        this.setStatus('未连接');
        freshSession();
        return;
      }
      if (this.wsClosedByUser) {
        this.setStatus('已断开');
        return;
      }
      if (event.reason === 'process_exited') {
        this.setStatus('已断开');
        return;
      }
      if (this.wsRetryCount >= this.wsMaxRetries) {
        this.setStatus('连接错误');
        return;
      }
      const delay = Math.min(
        this.wsRetryBaseDelay * Math.pow(2, this.wsRetryCount),
        this.wsRetryMaxDelay,
      );
      this.wsRetryCount += 1;
      this.setStatus(`连接断开，正在重试 (${this.wsRetryCount}/${this.wsMaxRetries})…`);
      this.wsRetryTimer = setTimeout(() => {
        this.wsRetryTimer = null;
        this.connect();
      }, delay);
    };
    ws.onmessage = (event) => {
      if (event.data instanceof ArrayBuffer) {
        const frame = new Uint8Array(event.data);
        const sequence = Number(new DataView(frame.buffer, frame.byteOffset, frame.byteLength).getBigUint64(0));
        this.output?.enqueue(sequence + frame.byteLength - 8, frame.slice(8));
      } else if (typeof event.data === 'string') {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'ready') {
            this.setStatus('已连接');
          } else if (msg.type === 'error') {
            this.setStatus(String(msg.error?.message || msg.message || '连接错误'));
          }
        } catch { /* malformed text frame — ignore */ }
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
      const oldFontSize = this.terminal.options.fontSize || 14;
      const newFontSize = Math.max(10, Math.min(MAX_TERMINAL_FONT_SIZE, oldFontSize + delta));
      this.terminal.options.fontSize = newFontSize;
      this.setPanelWidth(scaleAgentPanelWidth(this.panelWidth, oldFontSize, newFontSize));
      this.refreshTerminalLayout();
    };
    const fontDown = document.getElementById(id('AgentFontDown'));
    if (fontDown) fontDown.onclick = () => adjustFont(-1);
    const fontUp = document.getElementById(id('AgentFontUp'));
    if (fontUp) fontUp.onclick = () => adjustFont(1);
    const reconnect = document.getElementById(id('AgentReconnect'));
    if (reconnect) reconnect.onclick = () => {
      this.clearWsRetryTimer();
      this.wsClosedByUser = true;
      this.socket?.close();
      this.socket = null;
      this.connect();
    };
  }

  private readPanelWidth(): number {
    const max = getAgentPanelWidthBounds(MAX_TERMINAL_FONT_SIZE).max;
    const raw = Number(localStorage.getItem('clawmate.agentPanelWidth') || 0);
    if (Number.isFinite(raw) && raw > 0) return Math.max(420, Math.min(max, raw));
    return Math.max(420, Math.min(max, window.innerWidth * 0.46));
  }

  private setPanelWidth(width: number, enforceReadableMinimum = true, bounds?: { min: number; max: number }): void {
    const b = bounds ?? getAgentPanelWidthBounds(this.terminal?.options.fontSize || 14);
    const min = enforceReadableMinimum ? b.min : 420;
    this.panelWidth = Math.round(Math.max(min, Math.min(b.max, width)));
    localStorage.setItem('clawmate.agentPanelWidth', String(this.panelWidth));
    if (this.config?.domPrefix === 'preview') this.applyPreviewPanelWidth();
    else syncMainAgentPanelLayout(this.isOpen(), this.panelWidth);
    this.refreshTerminalLayout();
  }

  private applyPreviewPanelWidth(): void {
    const grid = document.querySelector<HTMLElement>('.preview-three-col');
    if (!grid) return;
    const parts = (grid.style.gridTemplateColumns || '240px 1fr 5px 750px').split(' ');
    parts[3] = `${this.panelWidth}px`;
    grid.style.gridTemplateColumns = parts.join(' ');
  }

  private bindResizeHandle(prefix: string): void {
    const id = prefix ? 'previewResizeHandle' : 'agentResizeHandle';
    const handle = document.getElementById(id) as HTMLElement | null;
    if (!handle || handle.dataset.agentResizeBound === 'true') return;
    handle.dataset.agentResizeBound = 'true';
    let startX = 0;
    let startWidth = this.panelWidth;
    const move = (event: PointerEvent) => {
      this.resizePanelToPointer(startWidth + (startX - event.clientX));
    };
    const stop = () => {
      handle.classList.remove('active');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', stop);
    };
    handle.addEventListener('pointerdown', (event) => {
      if (window.innerWidth <= 768) return;
      event.preventDefault();
      startX = event.clientX;
      startWidth = this.panelWidth;
      handle.classList.add('active');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', stop, { once: true });
    });
  }

  private bindChat(prefix: string): void {
    const input = document.getElementById(prefix ? 'previewAgentChatInput' : 'agentChatInput') as HTMLTextAreaElement | null;
    const send = document.getElementById(prefix ? 'previewAgentChatSend' : 'agentChatSend');
    const submit = () => {
      const text = input?.value.trim() || '';
      if (!text) return;
      this.openclaw.sendText(text);
      if (input) input.value = '';
      input?.focus();
    };
    if (input) input.onkeydown = (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submit();
      }
    };
    if (send) send.onclick = submit;
  }

  private updateTitle(): void {
    if (!this.config) return;
    const prefix = this.config.domPrefix === 'preview' ? 'preview' : '';
    const title = document.getElementById(prefix ? 'previewAgentTitle' : 'agentPanelTitle');
    if (title) title.textContent = formatAgentScope(this.config.backend, this.config.rootId, this.config.dir);
  }

  private injectFileContext(fileContext: AgentFileContext | undefined, prefix: string): void {
    const path = String(fileContext?.path || '').trim().replace(/^@+/, '');
    if (!path || !this.config) return;
    const context = `@${path}\n`;
    const generation = this.contextGeneration;
    if (this.config.backend === 'openclaw') {
      const input = document.getElementById(prefix ? 'previewAgentChatInput' : 'agentChatInput') as HTMLTextAreaElement | null;
      if (input && !input.value && generation === this.contextGeneration) {
        input.value = context;
        input.focus();
      }
      return;
    }
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.sendInput(new TextEncoder().encode(context));
    } else {
      this.pendingFileContext = context;
    }
  }

  /** Derive a stable scope key from the current config for message caching. */
  private _openClawScopeKey(): string {
    const cfg = this.config;
    if (!cfg) return '';
    return this._scopeKey(cfg.rootId, cfg.dir, cfg.project, cfg.backend);
  }

  private _scopeKey(rootId: string, dir: string, project?: string, backend?: AgentInitOptions['backend']): string {
    const scope = `${rootId || 'root'}:${agentProjectScope(dir, project)}`;
    return backend ? `${backend}:${scope}` : scope;
  }

  private readBackendPreference(scopeKey: string, fallback: AgentInitOptions['backend']): AgentInitOptions['backend'] {
    if (!isAgentBackend(fallback)) return 'claude';
    try {
      const raw = localStorage.getItem(AGENT_BACKEND_PREFERENCES_STORAGE_KEY);
      if (!raw) return fallback;
      const values: unknown = JSON.parse(raw);
      if (!values || typeof values !== 'object' || Array.isArray(values)) return fallback;
      const preferred = (values as Record<string, unknown>)[scopeKey];
      return isAgentBackend(preferred) ? preferred : fallback;
    } catch {
      return fallback;
    }
  }

  private saveBackendPreference(scopeKey: string, backend: AgentInitOptions['backend']): void {
    if (!scopeKey || !isAgentBackend(backend)) return;
    try {
      const raw = localStorage.getItem(AGENT_BACKEND_PREFERENCES_STORAGE_KEY);
      const values: Record<string, unknown> = raw ? JSON.parse(raw) : {};
      if (!values || typeof values !== 'object' || Array.isArray(values)) return;
      values[scopeKey] = backend;
      localStorage.setItem(AGENT_BACKEND_PREFERENCES_STORAGE_KEY, JSON.stringify(values));
    } catch {
      // localStorage is optional; backend switching must still work without it.
    }
  }

  private resetScopeState(prefix: string, oldScopeKey?: string): void {
    this.contextGeneration += 1;
    this.openclaw.close();
    this.wsClosedByUser = true;
    this.stopHeartbeat();
    this.clearWsRetryTimer();
    this.socket?.close();
    this.socket = null;
    this.disposeTerminal();
    this.clearOpenClawMessages(prefix, oldScopeKey);
    this.lastOutputAck = 0;
    this.setStatus('未连接');
  }

  /** Save current messages to per‑scope cache and clear the message list.
   *
   *  @param prefix - DOM prefix for the chat messages container.
   *  @param scopeKey - Optional explicit scope key to save under.
   *         When omitted, uses the current config's scope (caller must
   *         ensure config hasn't been changed yet, or pass the old key).
   */
  private clearOpenClawMessages(prefix: string, scopeKey?: string): void {
    const key = scopeKey ?? this._openClawScopeKey();
    if (key && this._openClawMessages.length) {
      this._savedOpenClawMessages.set(key, [...this._openClawMessages]);
    }
    this._openClawMessages.length = 0;
    const messages = document.getElementById(prefix ? 'previewAgentChatMessages' : 'agentChatMessages');
    if (messages) messages.replaceChildren();
    this.openclawInfo = null;
    this.openclawAssistant = null;
  }

  private handleOpenClawMessage(message: OpenClawMessage, prefix: string): void {
    // Buffer every message so we can replay on reconnect.
    this._openClawMessages.push({ ...message });
    const messages = document.getElementById(prefix ? 'previewAgentChatMessages' : 'agentChatMessages');
    if (!messages) return;
    const type = String(message.type || '');
    if (type === 'info') {
      const text = String(message.text || '').replace(/\s*\n\s*/g, ' · ');
      if (!this.openclawInfo || !this.openclawInfo.isConnected) {
        this.openclawInfo = document.createElement('div');
        this.openclawInfo.className = 'agent-chat-info';
        messages.appendChild(this.openclawInfo);
      }
      this.openclawInfo.textContent = text;
      messages.scrollTop = messages.scrollHeight;
      return;
    }
    if (type === 'error') {
      this.appendChat(messages, 'error', `✕ ${String(message.text || 'OpenClaw error')}`);
      return;
    }
    if (type === 'user') {
      this.openclawAssistant = null;
      this.appendChat(messages, type, String(message.text || ''));
      return;
    }
    if (type === 'assistant_replace') {
      if (!this.openclawAssistant || !this.openclawAssistant.isConnected) {
        this.openclawAssistant = document.createElement('div');
        this.openclawAssistant.className = 'agent-chat-msg agent-chat-assistant';
        messages.appendChild(this.openclawAssistant);
      }
      const text = String(message.text || '');
      this.openclawAssistant.dataset.rawText = text;
      this.renderAssistant(this.openclawAssistant, text);
      messages.scrollTop = messages.scrollHeight;
      return;
    }
    if (type === 'assistant') {
      if (!this.openclawAssistant || !this.openclawAssistant.isConnected) {
        this.openclawAssistant = document.createElement('div');
        this.openclawAssistant.className = 'agent-chat-msg agent-chat-assistant';
        messages.appendChild(this.openclawAssistant);
      }
      const text = `${this.openclawAssistant.dataset.rawText || ''}${String(message.text || '')}`;
      this.openclawAssistant.dataset.rawText = text;
      this.renderAssistant(this.openclawAssistant, text);
      if (message.final) this.openclawAssistant = null;
      messages.scrollTop = messages.scrollHeight;
    }
  }

  private renderAssistant(element: HTMLElement, text: string): void {
    const html = renderOpenClawMarkdown(text);
    if (html === null) {
      element.textContent = text;
      return;
    }
    element.innerHTML = html;
  }

  private appendChat(container: HTMLElement, role: string, text: string): void {
    const item = document.createElement('div');
    item.className = `agent-chat-msg agent-chat-${role}`;
    item.textContent = text;
    container.appendChild(item);
    container.scrollTop = container.scrollHeight;
  }

  private toggleHistory(prefix: string): void {
    const panelId = prefix ? 'previewAgentHistoryOverlay' : 'agentHistoryOverlay';
    let overlay = document.getElementById(panelId);
    if (!overlay) {
      overlay = document.createElement('section');
      overlay.id = panelId;
      overlay.className = 'agent-history-overlay hidden';
      overlay.innerHTML = '<div class="agent-history-overlay-header"><div class="agent-history-list-header"><span class="agent-history-overlay-title agent-history-header-label"><svg class="agent-history-title-icon agent-history-header-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"></circle><path d="M12 7v5l3 2"></path></svg><span>历史会话</span></span><div class="agent-history-controls"><span class="agent-history-search-wrap"><input class="agent-history-search-input agent-header-search" type="search" placeholder="搜索会话内容…" aria-label="搜索历史会话"><button class="agent-history-search-clear" type="button" aria-label="清除搜索"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 4 10 11"></path><path d="M10 11l-6 2"></path><path d="M10 11l-4 5"></path><path d="M10 11l-1 7"></path><path d="M10 11l2 7"></path><path d="M10 11l5 5"></path><path d="M10 11l7 2"></path></svg></button></span><select class="agent-history-backend-input agent-backend-select" aria-label="按 backend 过滤"><option value="">全部</option><option value="claude">Claude</option><option value="codex">Codex</option><option value="openclaw">OpenClaw</option></select></div><button class="agent-history-overlay-close agent-history-header-close" type="button" aria-label="关闭历史会话"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"></path></svg></button></div><div class="agent-history-detail-header" hidden><button class="agent-history-back agent-history-header-label" type="button"><svg class="agent-history-header-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6"></path></svg><span>历史列表</span></button><span class="agent-history-detail-title"></span><button class="agent-history-detail-close agent-history-header-close" type="button" aria-label="关闭历史会话"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"></path></svg></button></div></div><div class="agent-history-overlay-body"><div class="agent-history-date-axis"></div><div class="agent-history-list"></div><div class="agent-history-pagination"><button class="agent-history-prev" type="button">‹ 上一页</button><span class="agent-history-page-info">0 / 0</span><button class="agent-history-next" type="button">下一页 ›</button></div><article class="agent-history-detail hidden"><div class="agent-history-detail-body"></div></article></div></div>';
      const panel = document.getElementById(prefix ? 'previewAgentPanel' : 'agentPanel');
      panel?.appendChild(overlay);
      overlay.querySelector('.agent-history-overlay-close')?.addEventListener('click', () => overlay?.classList.add('hidden'));
      overlay.querySelector('.agent-history-back')?.addEventListener('click', () => {
        this.showHistoryList(overlay!);
      });
      overlay.querySelector('.agent-history-detail-close')?.addEventListener('click', () => overlay?.classList.add('hidden'));
      overlay.querySelector('.agent-history-search-input')?.addEventListener('input', (event) => {
        this.historyQuery = (event.target as HTMLInputElement).value.trim();
        this.loadHistory(overlay!, true);
      });
      overlay.querySelector('.agent-history-search-clear')?.addEventListener('click', () => {
        const input = overlay?.querySelector<HTMLInputElement>('.agent-history-search-input');
        if (!input) return;
        input.value = '';
        this.historyQuery = '';
        this.loadHistory(overlay!, true);
        input.focus();
      });
      overlay.querySelector('.agent-history-backend-input')?.addEventListener('change', (event) => {
        this.historyBackend = (event.target as HTMLSelectElement).value;
        this.loadHistory(overlay!, true);
      });
      overlay.querySelector('.agent-history-prev')?.addEventListener('click', () => {
        this.historyOffset = Math.max(0, this.historyOffset - this.historyLimit);
        this.loadHistory(overlay!, false);
      });
      overlay.querySelector('.agent-history-next')?.addEventListener('click', () => {
        this.historyOffset += this.historyLimit;
        this.loadHistory(overlay!, false);
      });
    }
    overlay.classList.toggle('hidden');
    if (overlay.classList.contains('hidden')) return;
    this.loadHistory(overlay, true);
  }

  private loadHistory(overlay: HTMLElement, resetPage = false): void {
    const list = overlay.querySelector('.agent-history-list');
    if (!list || !this.config) return;
    this.showHistoryList(overlay);
    if (resetPage) this.historyOffset = 0;
    overlay.querySelector('.agent-history-list')?.classList.remove('hidden');
    overlay.querySelector('.agent-history-detail')?.classList.add('hidden');
    list.innerHTML = '<div class="agent-history-loading">加载中…</div>';
    const requestId = ++this.historyRequest;
    const baseQuery = new URLSearchParams({
      root: this.config.rootId,
      dir: this.config.dir,
      q: this.historyQuery,
      backend: this.historyBackend,
      limit: String(this.historyLimit),
      offset: String(this.historyOffset),
    });
    const loadPage = (date = '') => {
      const query = new URLSearchParams(baseQuery);
      if (date) query.set('date', date);
      fetch(`/api/clawmate/agent/sessions?${query.toString()}`)
      .then((response) => response.json())
      .then((data) => {
        if (requestId !== this.historyRequest) return;
        this.renderHistoryPage(overlay, data, !!this.historyQuery);
      })
      .catch(() => { if (requestId === this.historyRequest) list.innerHTML = '<div class="agent-history-loading">历史会话加载失败</div>'; });
    };
    if (this.historyQuery) {
      this.renderHistoryDateAxis(overlay, false);
      loadPage();
      return;
    }
    if (!resetPage && this.historyDates.length) {
      this.renderHistoryDateAxis(overlay, true);
      loadPage(this.historyDates[this.historySelectedDateIndex]);
      return;
    }
    fetch(`/api/clawmate/agent/sessions/dates?${new URLSearchParams({ root: this.config.rootId, dir: this.config.dir }).toString()}`)
      .then((response) => response.json())
      .then((data) => {
        if (requestId !== this.historyRequest) return;
        if (!Array.isArray(data.dates)) {
          // Keep the adapter tolerant of older test/custom API responses.
          this.renderHistoryDateAxis(overlay, false);
          this.renderHistoryPage(overlay, data, false);
          return;
        }
        this.historyDates = data.dates as string[];
        this.historySelectedDateIndex = Math.min(this.historySelectedDateIndex, Math.max(0, this.historyDates.length - 1));
        this.historyAxisScrollIndex = Math.min(this.historyAxisScrollIndex, Math.max(0, this.historyDates.length - 1));
        this.renderHistoryDateAxis(overlay, true);
        if (this.historyDates.length) loadPage(this.historyDates[this.historySelectedDateIndex]);
        else this.renderHistoryPage(overlay, { sessions: [], total: 0 }, false);
      })
      .catch(() => { if (requestId === this.historyRequest) list.innerHTML = '<div class="agent-history-loading">历史会话加载失败</div>'; });
  }

  private renderHistoryDateAxis(overlay: HTMLElement, visible: boolean): void {
    const axis = overlay.querySelector<HTMLElement>('.agent-history-date-axis');
    if (!axis) return;
    axis.replaceChildren();
    axis.hidden = !visible || !this.historyDates.length;
    if (!axis.hidden) {
      const availableWidth = Math.max(240, (axis.clientWidth || 520) - 60);
      const maxVisible = Math.max(3, Math.floor(availableWidth / 58));
      const needsArrows = this.historyDates.length > maxVisible;
      if (needsArrows) {
        const previous = document.createElement('button');
        previous.type = 'button';
        previous.className = 'agent-history-date-arrow';
        previous.textContent = '‹';
        previous.title = '更早日期';
        previous.disabled = this.historyAxisScrollIndex <= 0;
        previous.addEventListener('click', () => {
          this.historyAxisScrollIndex = Math.max(0, this.historyAxisScrollIndex - maxVisible);
          this.renderHistoryDateAxis(overlay, true);
        });
        axis.appendChild(previous);
      }
      const buttons = document.createElement('div');
      buttons.className = 'agent-history-date-btns';
      const visibleDates = this.historyDates.slice(
        needsArrows ? this.historyAxisScrollIndex : 0,
        needsArrows ? this.historyAxisScrollIndex + maxVisible : undefined,
      );
      visibleDates.forEach((date, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'agent-history-date-btn';
        const actualIndex = this.historyAxisScrollIndex + index;
        button.classList.toggle('active', actualIndex === this.historySelectedDateIndex);
        button.textContent = formatHistoryDateLabel(date);
        button.addEventListener('click', () => {
          this.historySelectedDateIndex = actualIndex;
          this.historyOffset = 0;
          this.loadHistory(overlay, false);
        });
        buttons.appendChild(button);
      });
      axis.appendChild(buttons);
      if (needsArrows) {
        const next = document.createElement('button');
        next.type = 'button';
        next.className = 'agent-history-date-arrow';
        next.textContent = '›';
        next.title = '更早日期';
        next.disabled = this.historyAxisScrollIndex + maxVisible >= this.historyDates.length;
        next.addEventListener('click', () => {
          this.historyAxisScrollIndex = Math.min(this.historyDates.length - maxVisible, this.historyAxisScrollIndex + maxVisible);
          this.renderHistoryDateAxis(overlay, true);
        });
        axis.appendChild(next);
      }
    }
  }

  private renderHistoryPage(overlay: HTMLElement, data: { sessions?: Array<Record<string, unknown>>; total?: number }, groupByDate: boolean): void {
    const list = overlay.querySelector('.agent-history-list');
    if (!list) return;
    const sessions = Array.isArray(data.sessions) ? data.sessions : [];
    const total = Number(data.total || 0);
    const prev = overlay.querySelector<HTMLButtonElement>('.agent-history-prev');
    const next = overlay.querySelector<HTMLButtonElement>('.agent-history-next');
    const pageInfo = overlay.querySelector('.agent-history-page-info');
    if (prev) prev.disabled = this.historyOffset <= 0;
    if (next) next.disabled = this.historyOffset + this.historyLimit >= total;
    if (pageInfo) pageInfo.textContent = total ? `${this.historyOffset + 1}–${Math.min(this.historyOffset + sessions.length, total)} / ${total}` : '0 / 0';
    list.replaceChildren();
    if (!sessions.length) {
      list.innerHTML = '<div class="agent-history-loading">暂无历史会话</div>';
      return;
    }
    const historySessions: HistorySession[] = sessions.map((session) => ({
      ...session,
      id: String(session.id || ''),
      state: String(session.state || session.status || 'ended'),
      started_at: Number(session.started_at || 0),
      title: String(session.title || ''),
    }));
    const groups = groupByDate ? groupHistorySessions(historySessions) : [{ label: '', sessions: historySessions }];
        groups.forEach((group) => {
          const groupEl = document.createElement('section');
          groupEl.className = 'agent-history-group';
          if (group.label) {
            const groupTitle = document.createElement('h3');
            groupTitle.className = 'agent-history-group-title';
            groupTitle.textContent = group.label;
            groupEl.appendChild(groupTitle);
          }
          group.sessions.forEach((session) => {
          const row = document.createElement('div');
          row.setAttribute('role', 'button');
          row.tabIndex = 0;
          row.className = 'agent-history-item';
          const icon = document.createElement('span');
          icon.className = 'agent-history-item-icon';
          icon.textContent = session.backend === 'openclaw' ? '✦' : '⌁';
          icon.setAttribute('aria-hidden', 'true');
          const copy = document.createElement('span');
          copy.className = 'agent-history-item-copy';
          const title = document.createElement('span');
          title.className = 'agent-history-item-title';
          title.textContent = String(session.title || `${session.backend || 'agent'}:${session.root || this.config?.rootId || 'root'}:${session.project || 'root'}`);
          const meta = document.createElement('span');
          meta.className = 'agent-history-item-meta';
          meta.textContent = formatHistoryRowMeta(session);
          copy.append(title, meta);
          const actions = document.createElement('span');
          actions.className = 'agent-history-item-actions';
          const exportButton = document.createElement('button');
          exportButton.type = 'button';
          exportButton.className = 'agent-history-action agent-history-export';
          exportButton.title = '导出会话';
          exportButton.ariaLabel = '导出会话';
          exportButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 21h14"></path></svg>';
          exportButton.addEventListener('click', (event) => {
            event.stopPropagation();
            void this.exportHistorySession(session);
          });
          const deleteButton = document.createElement('button');
          deleteButton.type = 'button';
          deleteButton.className = 'agent-history-action agent-history-delete';
          deleteButton.title = '删除会话';
          deleteButton.ariaLabel = '删除会话';
          deleteButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15"></path></svg>';
          deleteButton.addEventListener('click', (event) => {
            event.stopPropagation();
            void this.deleteHistorySession(overlay!, session);
          });
          actions.append(exportButton, deleteButton);
          row.append(icon, copy, actions);
          const openDetail = () => this.openHistoryDetail(overlay!, session);
          row.addEventListener('click', openDetail);
          row.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              openDetail();
            }
          });
          groupEl.appendChild(row);
          });
          list.appendChild(groupEl);
        });
  }

  private openHistoryDetail(overlay: HTMLElement, session: Record<string, unknown>): void {
    if (!this.config) return;
    const list = overlay.querySelector('.agent-history-list');
    const detail = overlay.querySelector('.agent-history-detail');
    const title = overlay.querySelector('.agent-history-detail-title');
    const body = overlay.querySelector('.agent-history-detail-body');
    if (!list || !detail || !title || !body) return;
    this.showHistoryDetail(overlay);
    title.textContent = String(session.title || `${session.backend || 'agent'}:${session.root || this.config.rootId}:${session.project || 'root'}`);
    body.textContent = '加载中…';
    const query = new URLSearchParams({
      root: String(session.root || this.config.rootId),
      project: String(session.project || ''),
      dir: this.config.dir,
    });
    fetch(`/api/clawmate/agent/sessions/${encodeURIComponent(String(session.id || ''))}/log?${query.toString()}`)
      .then((response) => response.json())
      .then((data) => {
        body.replaceChildren();
        const turns = Array.isArray(data.turns) ? data.turns : [];
        if (!turns.length) {
          body.textContent = '该会话没有可显示的内容';
          return;
        }
        turns.forEach((turn: { role?: string; content?: string }) => {
          const item = document.createElement('div');
          item.className = `agent-history-turn agent-history-turn-${turn.role === 'assistant' ? 'assistant' : 'user'}`;
          const meta = document.createElement('div');
          meta.className = 'agent-history-turn-meta';
          const round = Number((turn as { turn_index?: number }).turn_index || 0);
          const timestamp = Number((turn as { ts?: number }).ts || 0);
          meta.textContent = `${round ? `第 ${round} 轮` : '未标注轮次'} · ${turn.role === 'assistant' ? 'Agent' : '你'}${timestamp ? ` · ${formatSessionDateTime(timestamp).slice(11)}` : ''}`;
          item.appendChild(meta);
          const content = String(turn.content || '');
          const contentElement = document.createElement('div');
          contentElement.className = 'agent-history-turn-content';
          if (turn.role === 'assistant') {
            const html = renderOpenClawMarkdown(content);
            if (html === null) contentElement.textContent = content;
            else contentElement.innerHTML = html;
          } else {
            contentElement.textContent = content;
          }
          item.appendChild(contentElement);
          body.appendChild(item);
        });
      })
      .catch(() => { body.textContent = '会话详情加载失败'; });
  }

  private showHistoryList(overlay: HTMLElement): void {
    overlay.querySelector<HTMLElement>('.agent-history-list-header')?.removeAttribute('hidden');
    overlay.querySelector<HTMLElement>('.agent-history-detail-header')?.setAttribute('hidden', 'true');
    overlay.querySelector<HTMLElement>('.agent-history-controls')?.removeAttribute('hidden');
    const axis = overlay.querySelector<HTMLElement>('.agent-history-date-axis');
    if (axis) axis.hidden = !this.historyDates.length || !!this.historyQuery;
    overlay.querySelector<HTMLElement>('.agent-history-list')?.classList.remove('hidden');
    overlay.querySelector<HTMLElement>('.agent-history-pagination')?.removeAttribute('hidden');
    overlay.querySelector<HTMLElement>('.agent-history-detail')?.classList.add('hidden');
  }

  private showHistoryDetail(overlay: HTMLElement): void {
    overlay.querySelector<HTMLElement>('.agent-history-list-header')?.setAttribute('hidden', 'true');
    overlay.querySelector<HTMLElement>('.agent-history-detail-header')?.removeAttribute('hidden');
    overlay.querySelector<HTMLElement>('.agent-history-date-axis')?.setAttribute('hidden', 'true');
    overlay.querySelector<HTMLElement>('.agent-history-list')?.classList.add('hidden');
    overlay.querySelector<HTMLElement>('.agent-history-pagination')?.setAttribute('hidden', 'true');
    overlay.querySelector<HTMLElement>('.agent-history-detail')?.classList.remove('hidden');
  }

  private async exportHistorySession(session: Record<string, unknown>): Promise<void> {
    if (!this.config) return;
    try {
      const query = this.historySessionQuery(session);
      const [detailResponse, logResponse] = await Promise.all([
        fetch(`/api/clawmate/agent/sessions/${encodeURIComponent(String(session.id || ''))}?${query}`),
        fetch(`/api/clawmate/agent/sessions/${encodeURIComponent(String(session.id || ''))}/log?${query}`),
      ]);
      if (!detailResponse.ok || !logResponse.ok) throw new Error('加载会话失败');
      const detail = await detailResponse.json();
      const log = await logResponse.json();
      const title = String(detail.meta?.title || detail.session_id || session.id || 'agent-session')
        .replace(/[\\/:*?"<>|]+/g, '-').trim() || 'agent-session';
      const lines = [`# ${title}`, ''];
      for (const turn of Array.isArray(log.turns) ? log.turns : []) {
        const round = Number(turn.turn_index || 0);
        const timestamp = Number(turn.ts || 0);
        lines.push(`## ${turn.role === 'assistant' ? 'Agent' : '你'}${round ? ` · 第 ${round} 轮` : ''}${timestamp ? ` · ${formatSessionDateTime(timestamp)}` : ''}`, '', String(turn.content || ''), '');
      }
      const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = `${title}.md`;
      link.click();
      URL.revokeObjectURL(url);
    } catch {
      window.alert('导出失败');
    }
  }

  private async deleteHistorySession(overlay: HTMLElement, session: Record<string, unknown>): Promise<void> {
    if (!window.confirm('确定删除此会话？')) return;
    try {
      const query = this.historySessionQuery(session);
      const response = await fetch(`/api/clawmate/agent/sessions/${encodeURIComponent(String(session.id || ''))}?${query}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('delete failed');
      this.loadHistory(overlay, true);
    } catch {
      window.alert('删除失败');
    }
  }

  private historySessionQuery(session: Record<string, unknown>): string {
    const query = new URLSearchParams({
      root: String(session.root || this.config?.rootId || ''),
      project: String(session.project || ''),
      dir: this.config?.dir || '',
    });
    return query.toString();
  }

  private setStatus(text: string): void {
    const prefix = this.config?.domPrefix === 'preview' ? 'preview' : '';
    const status = document.getElementById(`${prefix}AgentStatus`);
    if (!status) return;
    status.textContent = text;
    // 红绿灯：已连接=绿，连接中=黄，其他=红
    if (text === '已连接') status.dataset.status = 'connected';
    else if (text === '连接中') status.dataset.status = 'connecting';
    else status.dataset.status = 'disconnected';
  }

  private clearWsRetryTimer(): void {
    if (this.wsRetryTimer !== null) {
      clearTimeout(this.wsRetryTimer);
      this.wsRetryTimer = null;
    }
  }

  /** Start sending application‑level heartbeat pings every 25 seconds.
   *  Intermediate proxies (nginx, Cloudflare, etc.) often have idle‑timeout
   *  settings between 60–120 s for WebSocket connections.  A heartbeat every
   *  25 s keeps the connection alive even during long stretches where no
   *  terminal data flows, without waking the backend for every frame. */
  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.sendControl({ type: 'heartbeat' });
    }, 25000);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private setTerminalToolbarVisible(prefix: string, visible: boolean): void {
    const toolbar = document.getElementById(prefix ? 'previewAgentToolbar' : 'AgentToolbar');
    const searchRow = document.getElementById(prefix ? 'previewAgentSearchRow' : 'AgentSearchRow');
    if (toolbar) toolbar.hidden = !visible;
    if (searchRow) searchRow.hidden = true;
  }

  private disposeTerminal(): void {
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    this.terminal?.dispose();
    this.terminal = null;
    this.fit = null;
    this.search = null;
    this.output = null;
    const prefix = this.config?.domPrefix === 'preview' ? 'preview' : '';
    const host = document.getElementById(prefix ? 'previewXtermContainer' : 'xtermContainer');
    if (host) host.innerHTML = '';
  }

  private observeTerminalHost(host?: HTMLElement): void {
    const target = host || document.getElementById(this.config?.domPrefix === 'preview' ? 'previewXtermContainer' : 'xtermContainer');
    if (!target || typeof ResizeObserver === 'undefined') return;
    this.resizeObserver?.disconnect();
    this.resizeObserver = new ResizeObserver(() => this.scheduleTerminalFit(target));
    this.resizeObserver.observe(target);
  }

  private scheduleTerminalFit(host?: HTMLElement): void {
    if (!this.fit) return;
    const target = host || document.getElementById(this.config?.domPrefix === 'preview' ? 'previewXtermContainer' : 'xtermContainer');
    if (!target) return;
    const fit = () => {
      const rect = target.getBoundingClientRect();
      if (rect.width > 80 && rect.height > 80) this.fit?.fit();
    };
    requestAnimationFrame(() => requestAnimationFrame(fit));
  }

  private refreshTerminalLayout(): void {
    this.scheduleTerminalFit();
    if (this.terminal) {
      this.terminal.refresh(0, Math.max(0, (this.terminal.rows || 1) - 1));
    }
  }

  private syncFontToPanelWidth(): void {
    if (!this.terminal) return;
    const current = this.terminal.options.fontSize || 14;
    const next = getFontSizeForAgentPanelWidth(this.panelWidth);
    const bounds = getAgentPanelWidthBounds(next);
    const readableWidth = Math.round(Math.max(bounds.min, Math.min(bounds.max, this.panelWidth)));
    if (readableWidth !== this.panelWidth) this.setPanelWidth(readableWidth, false, bounds);
    if (current === next) return;
    this.terminal.options.fontSize = next;
    this.refreshTerminalLayout();
  }

  private resizePanelToPointer(width: number): void {
    const nextFontSize = getFontSizeForAgentPanelWidth(width);
    const bounds = getAgentPanelWidthBounds(nextFontSize);
    const nextWidth = Math.round(Math.max(bounds.min, Math.min(bounds.max, width)));
    this.setPanelWidth(nextWidth, false, bounds);
    if (this.terminal && (this.terminal.options.fontSize || 14) !== nextFontSize) {
      this.terminal.options.fontSize = nextFontSize;
      this.refreshTerminalLayout();
    }
  }

  private startFreshSession(): void {
    if (!this.config) return;
    const wasOpen = this.isOpen();
    this.openclaw.close();
    if (this.config.backend === 'openclaw') {
      this.openclawSessionId = crypto.randomUUID();
      this.clearOpenClawMessages(this.config.domPrefix === 'preview' ? 'preview' : '');
    }
    this.wsClosedByUser = true;
    this.clearWsRetryTimer();
    const openFreshSession = () => {
      this.disposeTerminal();
      if (wasOpen) this.open();
    };
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.pendingFreshSession = openFreshSession;
      this.socket.send(JSON.stringify({ v: 2, type: 'terminate', reason: 'replaced' }));
      return;
    }
    this.socket?.close();
    this.socket = null;
    openFreshSession();
  }

  private sendControl(message: Record<string, unknown>): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ v: 2, ...message }));
  }

  private sendInput(data: Uint8Array): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(encodeInputFrame(this.nextSequence++, data));
  }
}
