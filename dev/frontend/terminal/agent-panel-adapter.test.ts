// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

vi.mock('@xterm/xterm', () => ({
  Terminal: class Terminal {},
}));

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: class FitAddon {},
}));

import { AgentPanelAdapter, formatAgentScope, getAgentPanelWidthBounds, getFontSizeForAgentPanelWidth, renderOpenClawMarkdown, scaleAgentPanelWidth, syncMainAgentPanelLayout } from './agent-panel-adapter';

describe('main agent panel layout', () => {
  it('uses the configured backend when no project preference exists', () => {
    localStorage.clear();
    document.body.innerHTML = '<select id="agentBackendSelect"><option value="claude">Claude</option><option value="codex">Codex</option><option value="openclaw">OpenClaw</option></select>';

    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root1', dir: 'project' });

    expect((document.getElementById('agentBackendSelect') as HTMLSelectElement).value).toBe('codex');
  });

  it('restores and persists the backend preference for a project scope', () => {
    localStorage.clear();
    localStorage.setItem('clawmate.agent.backend-preferences.v1', JSON.stringify({
      'root1:project': 'claude',
    }));
    document.body.innerHTML = '<select id="agentBackendSelect"><option value="claude">Claude</option><option value="codex">Codex</option><option value="openclaw">OpenClaw</option></select>';

    const first = new AgentPanelAdapter();
    first.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root1', dir: 'project' });
    expect((document.getElementById('agentBackendSelect') as HTMLSelectElement).value).toBe('claude');

    first.setBackend('openclaw');
    expect(JSON.parse(localStorage.getItem('clawmate.agent.backend-preferences.v1') || '{}')['root1:project']).toBe('openclaw');

    const second = new AgentPanelAdapter();
    second.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root1', dir: 'project' });
    expect((document.getElementById('agentBackendSelect') as HTMLSelectElement).value).toBe('openclaw');
  });

  it('ignores malformed or unsupported project backend preferences', () => {
    localStorage.setItem('clawmate.agent.backend-preferences.v1', '{bad json');
    document.body.innerHTML = '<select id="agentBackendSelect"><option value="claude">Claude</option><option value="codex">Codex</option><option value="openclaw">OpenClaw</option></select>';
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root1', dir: 'project' });
    expect((document.getElementById('agentBackendSelect') as HTMLSelectElement).value).toBe('codex');

    localStorage.setItem('clawmate.agent.backend-preferences.v1', JSON.stringify({ 'root1:project': 'invalid' }));
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root1', dir: 'project' });
    expect((document.getElementById('agentBackendSelect') as HTMLSelectElement).value).toBe('codex');
  });

  it('clears the old root chat before opening the new root scope', () => {
    localStorage.clear();
    class FakeWebSocket {
      static OPEN = 1;
      readyState = 0;
      close = vi.fn();
      send = vi.fn();
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
    document.body.innerHTML = `
      <aside id="agentPanel"></aside>
      <div id="agentChatView"></div>
      <div id="agentChatMessages"></div>
      <textarea id="agentChatInput"></textarea>
      <select id="agentBackendSelect"><option value="openclaw">OpenClaw</option></select>
      <span id="agentPanelTitle"></span><span id="agentStatus"></span>
    `;
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'openclaw', wsUrl: 'ws://test', rootId: 'root1', dir: 'project' });
    document.getElementById('agentPanel')?.classList.remove('hidden');
    (adapter as any).handleOpenClawMessage({ type: 'user', text: 'root1 message' }, '');
    expect(document.getElementById('agentChatMessages')?.textContent).toContain('root1 message');

    adapter.updateRoot('root2', '', '');

    expect(document.getElementById('agentChatMessages')?.textContent).toBe('');
    vi.unstubAllGlobals();
  });

  it('resets the terminal scope when root changes while the panel is closed', () => {
    localStorage.clear();
    document.body.innerHTML = '<aside id="agentPanel" class="hidden"></aside><span id="agentPanelTitle"></span><span id="agentStatus"></span>';
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root1', dir: 'project' });
    const resetScopeState = vi.spyOn(adapter as any, 'resetScopeState');

    adapter.updateRoot('root2', '', '');

    expect(resetScopeState).toHaveBeenCalledOnce();
    expect(resetScopeState).toHaveBeenCalledWith('', 'codex:root1:project');
  });

  it('formats the visible backend root project scope', () => {
    expect(formatAgentScope('claude', 'webprojects', 'clawmate/src')).toBe('claude:webprojects:clawmate');
    expect(formatAgentScope('openclaw', 'webprojects', '')).toBe('openclaw:webprojects:root');
  });
  it('allocates the right grid column when the v2 panel opens', () => {
    document.body.innerHTML = `
      <div class="content">
        <aside id="sidebar"></aside>
        <aside id="agentPanel" class="agent-panel"></aside>
      </div>
    `;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });

    syncMainAgentPanelLayout(true);

    expect(document.querySelector('.content')?.getAttribute('style')).toContain(
      '240px 1fr 5px minmax(420px, 662.4px)',
    );
    expect(document.body.classList.contains('agent-open')).toBe(true);
  });

  it('uses the persisted draggable width when expanding the panel', () => {
    document.body.innerHTML = '<div class="content"><aside id="sidebar"></aside></div>';
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
    syncMainAgentPanelLayout(true, 780);
    expect(document.querySelector('.content')?.getAttribute('style')).toContain('minmax(420px, 780px)');
  });

  it('keeps the topbar toggle inactive when the panel close button closes the panel', () => {
    document.body.innerHTML = `
      <div class="content"></div>
      <aside id="agentPanel"></aside>
      <button id="btnToggleAgent" class="active"></button>
      <button id="btnCloseAgent"></button>
      <span id="agentStatus"></span>
    `;
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });
    document.getElementById('agentPanel')?.classList.remove('hidden');
    adapter.close();
    expect(document.getElementById('agentPanel')?.classList.contains('hidden')).toBe(true);
    expect(document.getElementById('btnToggleAgent')?.classList.contains('active')).toBe(false);
  });

  it('closes the WebSocket without terminating the session when closing the agent panel', () => {
    class FakeWebSocket {
      static OPEN = 1;
      readyState = FakeWebSocket.OPEN;
      send = vi.fn();
      close = vi.fn();
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
    document.body.innerHTML = '<div class="content"></div><aside id="agentPanel"></aside><span id="agentStatus"></span>';
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });
    const socket = new FakeWebSocket();
    (adapter as any).socket = socket;

    adapter.close();

    // Panel close no longer sends terminate — session stays alive for continuity
    expect(socket.send).not.toHaveBeenCalled();
    expect(socket.close).toHaveBeenCalledOnce();
    vi.unstubAllGlobals();
  });

  it('waits for v2 termination before opening a fresh session', () => {
    class FakeWebSocket {
      static OPEN = 1;
      readyState = FakeWebSocket.OPEN;
      send = vi.fn();
      close = vi.fn();
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
    document.body.innerHTML = '<aside id="agentPanel" class="hidden"></aside><span id="agentStatus"></span>';
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });
    const socket = new FakeWebSocket();
    (adapter as any).socket = socket;

    (adapter as any).startFreshSession();

    expect(socket.send).toHaveBeenCalledWith(JSON.stringify({ v: 2, type: 'terminate', reason: 'replaced' }));
    expect(socket.close).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('does not reconnect after the CLI exits normally', () => {
    class FakeWebSocket {
      static OPEN = 1;
      static last: FakeWebSocket | null = null;
      readyState = 0;
      onopen: (() => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      send = vi.fn();
      close = vi.fn();
      constructor() { FakeWebSocket.last = this; }
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
    document.body.innerHTML = '<span id="AgentStatus"></span>';
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });

    (adapter as any).connect();
    FakeWebSocket.last?.onclose?.({ reason: 'process_exited' } as CloseEvent);

    expect(document.getElementById('AgentStatus')?.textContent).toBe('已断开');
    vi.unstubAllGlobals();
  });

  it('derives width bounds from font size and readable terminal columns', () => {
    document.body.innerHTML = '<div class="content"></div>';
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1920 });
    // When canvas measureText is unavailable (jsdom), the code falls back to
    // a 0.625 factor (= 5/8) which is a safer estimate than the old 0.6 for
    // typical monospace fonts like JetBrains Mono.  Both the min and max use
    // the fallback when measurement returns 0.
    //
    // The width calculation mirrors xterm's internal dimension math:
    //   cssCanvasWidth = Math.round(cellWidth × 84)
    //   minWidth       = cssCanvasWidth + scrollbar(14) + flatSafety(8)
    // This matches FitAddon's floor‑division logic without a per‑cell margin.
    const CHROME = 14 + 8; // XTERM_SCROLLBAR_WIDTH + FLAT_SAFETY_MARGIN
    const expectedMin10 = Math.round(10 * 0.625 * 84) + CHROME; // 547
    const expectedMin20 = Math.round(20 * 0.625 * 84) + CHROME; // 1072
    expect(getAgentPanelWidthBounds(10).min).toBe(expectedMin10);
    expect(getAgentPanelWidthBounds(20).min).toBe(expectedMin20);
    // max is capped at availableMax when no sidebar on 1920px:
    //   1920 − 0(sidebar) − 315 − 5 = 1600
    // Since maxReadable (1072) < 1600, max = max(min, 1072).
    expect(getAgentPanelWidthBounds(20).max).toBe(expectedMin20);
    expect(scaleAgentPanelWidth(524, 10, 20)).toBe(1048);
    expect(getFontSizeForAgentPanelWidth(expectedMin10)).toBe(10);
    // width = 700 → largest fontSize whose bounds.min ≤ 700
    expect(getFontSizeForAgentPanelWidth(700)).toBe(12);
    expect(getFontSizeForAgentPanelWidth(expectedMin20)).toBe(20);
  });

  it('renders OpenClaw Markdown while keeping line breaks', () => {
    const use = vi.fn().mockReturnThis();
    (window as any).markdownit = vi.fn(() => ({
      use,
      render: (value: string) => `<p>${value.replace(/\n/g, '<br>')}</p>`,
    })) as any;
    (window as any).DOMPurify = { sanitize: (value: string) => value };

    expect(renderOpenClawMarkdown('## 标题\n\n- 项目')).toBe('<p>## 标题<br><br>- 项目</p>');
    expect((window as any).markdownit).toHaveBeenCalledWith({
      html: false,
      linkify: true,
      typographer: true,
      breaks: true,
    });
  });

  it('prefills preview file context without sending it', () => {
    class FakeWebSocket {
      static OPEN = 1;
      static last: FakeWebSocket | null = null;
      readyState = 0;
      onopen: (() => void) | null = null;
      onclose: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: { data: string }) => void) | null = null;
      send = vi.fn();
      close = vi.fn();
      constructor() { FakeWebSocket.last = this; }
    }
    vi.stubGlobal('WebSocket', FakeWebSocket);
    document.body.innerHTML = `
      <aside id="previewAgentPanel" class="hidden"></aside>
      <select id="previewAgentBackendSelect"><option value="openclaw">OpenClaw</option></select>
      <span id="previewAgentTitle"></span><span id="previewAgentStatus"></span>
      <div id="previewXtermContainer"></div><div id="previewAgentChatView" class="hidden">
        <div id="previewAgentChatMessages"></div>
        <textarea id="previewAgentChatInput"></textarea><button id="previewAgentChatSend"></button>
      </div>
      <button id="previewBtnCloseAgent"></button><button id="previewBtnNewAgentSession"></button>
      <button id="previewBtnAgentHistory"></button><div id="previewAgentToolbar"></div><div id="previewAgentSearchRow"></div>
    `;
    const adapter = new AgentPanelAdapter();
    adapter.init({ domPrefix: 'preview', backend: 'openclaw', wsUrl: 'ws://gateway.test/agent', rootId: 'root', dir: 'project' });
    adapter.open('root', 'project', { path: 'src/main.ts' });
    expect((document.getElementById('previewAgentChatInput') as HTMLTextAreaElement).value).toBe('@src/main.ts\n');
    expect(FakeWebSocket.last?.send).not.toHaveBeenCalled();
    adapter.close();
    vi.unstubAllGlobals();
  });

  it('renders grouped history rows with metadata and export/delete actions', async () => {
    document.body.innerHTML = `
      <aside id="agentPanel"><button id="btnAgentHistory"></button></aside>
      <span id="agentPanelTitle"></span><span id="agentStatus"></span>
    `;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ json: async () => ({ dates: ['2026-07-11'] }) })
      .mockResolvedValueOnce({ json: async () => ({
        total: 1,
        sessions: [{
          id: 'session-1', title: 'Fix history', backend: 'codex', state: 'ended',
          started_at: new Date(2099, 0, 1, 9, 8, 7).getTime() / 1000,
          turn_count: 2, instruction_count: 3, first_ts: 100, last_ts: 220,
          root: 'root', project: 'project',
        }],
      }) });
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });
    document.getElementById('btnAgentHistory')?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const overlay = document.getElementById('agentHistoryOverlay')!;
    expect(overlay.querySelector('.agent-history-overlay-header .agent-history-controls')).toBeTruthy();
    expect(overlay.querySelector('.agent-history-search-clear')).toBeTruthy();
    expect(Array.from(overlay.querySelectorAll<HTMLSelectElement>('.agent-history-backend-input option'))
      .map((option) => option.value)).toEqual(['', 'claude', 'codex']);
    expect(overlay.textContent).toContain('2099-01-01');
    expect(overlay.querySelector('.agent-history-list .agent-history-group-title')).toBeNull();
    expect(overlay.textContent).toContain('Fix history');
    expect(overlay.querySelector('.agent-history-item-meta')?.textContent).not.toContain('session-1');
    expect(overlay.textContent).not.toContain('codex · ');
    expect(overlay.textContent).toMatch(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/);
    expect(overlay.textContent).toContain('2轮对话');
    expect(overlay.textContent).toContain('3条指令');
    expect(overlay.textContent).not.toContain('查看');
    expect(overlay.querySelector('.agent-history-export')).toBeTruthy();
    expect(overlay.querySelector('.agent-history-delete')).toBeTruthy();
    overlay.querySelector<HTMLButtonElement>('.agent-history-overlay-close')?.click();
    expect(overlay.classList.contains('hidden')).toBe(true);
    vi.unstubAllGlobals();
  });

  it('shows date group titles only in search mode', async () => {
    document.body.innerHTML = `
      <aside id="agentPanel"><button id="btnAgentHistory"></button></aside>
      <span id="agentPanelTitle"></span><span id="agentStatus"></span>
    `;
    const session = {
      id: 'search-session', title: 'Search result', backend: 'codex', state: 'ended',
      started_at: new Date(2099, 0, 1, 9, 0, 0).getTime() / 1000,
      turn_count: 1, instruction_count: 1, root: 'root', project: 'project',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ json: async () => ({ dates: ['2026-07-11'] }) })
      .mockResolvedValueOnce({ json: async () => ({ total: 1, sessions: [session] }) })
      .mockResolvedValueOnce({ json: async () => ({ total: 1, sessions: [session] }) });
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });
    document.getElementById('btnAgentHistory')?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    const search = document.querySelector<HTMLInputElement>('.agent-history-search-input')!;
    search.value = 'Search';
    search.dispatchEvent(new Event('input', { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect((document.querySelector('.agent-history-date-axis') as HTMLElement)?.hidden).toBe(true);
    expect(document.querySelector('.agent-history-list .agent-history-group-title')?.textContent).toBe('2099-01-01');
    vi.unstubAllGlobals();
  });

  it('opens detail by row click and labels each message with round and time', async () => {
    document.body.innerHTML = `
      <aside id="agentPanel"><button id="btnAgentHistory"></button></aside>
      <span id="agentPanelTitle"></span><span id="agentStatus"></span>
    `;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ json: async () => ({ dates: ['2026-07-11'] }) })
      .mockResolvedValueOnce({ json: async () => ({ total: 1, sessions: [{
        id: 'session-1', title: 'Conversation', backend: 'codex', state: 'ended',
        started_at: 1781139600, turn_count: 1, instruction_count: 1,
        root: 'root', project: 'project',
      }] }) })
      .mockResolvedValueOnce({ json: async () => ({ turns: [
        { role: 'user', turn_index: 1, ts: new Date(2026, 6, 11, 9, 8, 7).getTime() / 1000, content: 'question' },
        { role: 'assistant', turn_index: 1, ts: new Date(2026, 6, 11, 9, 8, 9).getTime() / 1000, content: 'answer' },
      ] }) });
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });
    document.getElementById('btnAgentHistory')?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector<HTMLButtonElement>('.agent-history-item')?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    const body = document.querySelector('.agent-history-detail-body')!;
    expect(body.textContent).toContain('第 1 轮');
    expect(body.textContent).toContain('09:08:07');
    expect(body.textContent).toContain('question');
    expect(body.textContent).toContain('answer');
    expect(document.querySelector('.agent-history-detail-title')?.textContent)
      .toBe('session-1');
    expect((document.querySelector('.agent-history-list-header') as HTMLElement)?.hidden).toBe(true);
    expect((document.querySelector('.agent-history-detail-header') as HTMLElement)?.hidden).toBe(false);
    expect((document.querySelector('.agent-history-pagination') as HTMLElement)?.hidden).toBe(true);
    expect((document.querySelector('.agent-history-date-axis') as HTMLElement)?.hidden).toBe(true);
    expect(document.querySelector('.agent-history-detail-close')).toBeTruthy();
    expect(document.querySelector('.agent-history-back')?.textContent).toContain('历史列表');
    document.querySelector<HTMLButtonElement>('.agent-history-detail-close')?.click();
    expect(document.getElementById('agentHistoryOverlay')?.classList.contains('hidden')).toBe(true);
    vi.unstubAllGlobals();
  });

  it('exports and deletes from row actions without opening detail', async () => {
    document.body.innerHTML = `
      <aside id="agentPanel"><button id="btnAgentHistory"></button></aside>
      <span id="agentPanelTitle"></span><span id="agentStatus"></span>
    `;
    const session = {
      id: 'session-1', title: 'Export me', backend: 'codex', state: 'ended',
      started_at: 1781139600, turn_count: 1, instruction_count: 1,
      root: 'root', project: 'project',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ dates: ['2026-07-11'] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ total: 1, sessions: [session] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ meta: { title: 'Export me' } }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ turns: [{ role: 'user', turn_index: 1, ts: 1, content: 'hello' }] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ dates: ['2026-07-11'] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ total: 0, sessions: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });
    document.getElementById('btnAgentHistory')?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    document.querySelector<HTMLButtonElement>('.agent-history-export')?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls[2][0]).toContain('/sessions/session-1?');
    expect(fetchMock.mock.calls[3][0]).toContain('/sessions/session-1/log?');
    document.querySelector<HTMLButtonElement>('.agent-history-delete')?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls[4][1]).toMatchObject({ method: 'DELETE' });
    anchorClick.mockRestore();
    vi.unstubAllGlobals();
  });

  it('advances the history page with the configured offset', async () => {
    document.body.innerHTML = `
      <aside id="agentPanel"><button id="btnAgentHistory"></button></aside>
      <span id="agentPanelTitle"></span><span id="agentStatus"></span>
    `;
    const sessions = Array.from({ length: 16 }, (_, index) => ({
      id: `session-${index}`, title: `Session ${index}`, backend: 'codex', state: 'ended',
      started_at: 1781139600 - index, turn_count: 1, instruction_count: 1,
      root: 'root', project: 'project',
    }));
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ dates: ['2026-07-11', '2026-07-10'] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ total: 16, sessions }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ total: 16, sessions: [sessions[15]] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ total: 0, sessions: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });
    document.getElementById('btnAgentHistory')?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(document.querySelector<HTMLButtonElement>('.agent-history-next')?.disabled).toBe(false);
    document.querySelector<HTMLButtonElement>('.agent-history-next')?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls[2][0]).toContain('offset=15');
    expect(document.querySelector('.agent-history-page-info')?.textContent).toContain('16 / 16');
    document.querySelectorAll<HTMLButtonElement>('.agent-history-date-btn')[1]?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(fetchMock.mock.calls[3][0]).toContain('date=2026-07-10');
    vi.unstubAllGlobals();
  });

  it('shows as many date-axis buttons as fit before adding arrows', async () => {
    document.body.innerHTML = `
      <aside id="agentPanel"><button id="btnAgentHistory"></button></aside>
      <span id="agentPanelTitle"></span><span id="agentStatus"></span>
    `;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ json: async () => ({ dates: ['2026-07-11', '2026-07-10', '2026-07-09', '2026-07-08'] }) })
      .mockResolvedValueOnce({ json: async () => ({ total: 1, sessions: [] }) });
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new AgentPanelAdapter();
    adapter.init({ backend: 'codex', wsUrl: 'ws://test', rootId: 'root', dir: 'project' });
    document.getElementById('btnAgentHistory')?.click();
    const axis = document.querySelector<HTMLElement>('.agent-history-date-axis')!;
    Object.defineProperty(axis, 'clientWidth', { configurable: true, value: 520 });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(axis.querySelectorAll('.agent-history-date-btn')).toHaveLength(4);
    expect(axis.querySelectorAll('.agent-history-date-arrow')).toHaveLength(0);
    vi.unstubAllGlobals();
  });
});
