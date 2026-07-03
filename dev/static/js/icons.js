/**
 * ClawMate Icon System — Lucide SVG Icons
 *
 * Usage:
 *   iconSVG('folder', 16)  →  '<svg width="16" height="16" ...>...</svg>'
 *   fileIconSVG(entry)      →  icon SVG for a file entry
 */

const ICONS = {
  // Navigation
  'chevron-left':  '<path d="m15 18-6-6 6-6"/>',
  'chevron-right': '<path d="m9 18 6-6-6-6"/>',
  'chevron-down':  '<path d="m6 9 6 6 6-6"/>',
  'arrow-up-down': '<path d="m21 16-4 4-4-4"/><path d="M17 20V4"/><path d="m3 8 4-4 4 4"/><path d="M7 4v16"/>',
  'menu':          '<line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="18" y2="18"/>',
  'x':             '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',

  // Files & Folders
  'folder':        '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  'folder-open':   '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
  'folder-project':'<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/><g fill="var(--accent)" stroke="var(--accent)"><path d="M10 10v7"/><path d="M10 10h3"/><path d="M13 10v3.5"/><path d="M10 13.5h3"/></g>',
  'file':          '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
  'file-text':     '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  'file-code':     '<path d="M10 12.5 8 15l2 2.5"/><path d="M14 12.5 16 15l-2 2.5"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>',
  'image':         '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
  'video':         '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
  'music':         '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  'archive':       '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',

  // Actions
  'search':        '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  'download':      '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/>',
  'trash-2':       '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/>',
  'pencil':        '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/>',
  'plus':          '<path d="M5 12h14"/><path d="M12 5v14"/>',
  'copy':          '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  'move':          '<polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" x2="22" y1="12" y2="12"/><line x1="12" x2="12" y1="2" y2="22"/>',
  'share':         '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" x2="12" y1="2" y2="15"/>',

  // UI
  'sun':           '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  'moon':          '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
  'sun-moon':      '<path d="M12 8a2.83 2.83 0 0 0 4 4 4 4 0 1 1-4-4Z"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  'log-out':       '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" x2="9" y1="12" y2="12"/>',
  'check-square':  '<path d="m9 11 3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  'layout-grid':   '<rect width="7" height="7" x="3" y="3" rx="1"/><rect width="7" height="7" x="14" y="3" rx="1"/><rect width="7" height="7" x="14" y="14" rx="1"/><rect width="7" height="7" x="3" y="14" rx="1"/>',
  'list':          '<line x1="8" x2="21" y1="6" y2="6"/><line x1="8" x2="21" y1="12" y2="12"/><line x1="8" x2="21" y1="18" y2="18"/><line x1="3" x2="3.01" y1="6" y2="6"/><line x1="3" x2="3.01" y1="12" y2="12"/><line x1="3" x2="3.01" y1="18" y2="18"/>',
  'message-square': '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  'book-open':     '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  'file-output':   '<path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M4 7V4a2 2 0 0 1 2-2h8.5L20 7.5V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3"/><path d="M4 14h6"/><path d="m7 11-3 3 3 3"/>',
  'terminal':      '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
  'clock':         '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',

  // Brand
  'lobster':       '<circle cx="12" cy="12" r="10"/><path d="M12 6v12"/><path d="M6 12h12"/>',  // placeholder
};

/**
 * Return an inline SVG string.
 * @param {string} name - icon name from ICONS map
 * @param {number} [size=16] - width & height in px
 * @param {string} [className] - optional CSS class
 * @returns {string} SVG markup
 */
function iconSVG(name, size, className) {
  size = size || 16;
  var body = ICONS[name];
  if (!body) {
    console.warn('icons.js: unknown icon "' + name + '"');
    return '';
  }
  var cls = className ? ' class="' + className + '"' : '';
  return '<svg' + cls + ' width="' + size + '" height="' + size + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + body + '</svg>';
}

/**
 * Return a colored letter tag (like Office W/X/P) scaled to size.
 * @param {string} label - text to display
 * @param {string} bg - background color
 * @param {string} fg - text color
 * @param {number} size - box size in px
 * @param {string} ff - font-family (sans-serif or monospace)
 * @returns {string} HTML span
 */
function _tag(label, bg, fg, size, ff) {
  var fs = Math.round(size * 0.38);
  var br = Math.round(size * 0.2);
  return '<span style="display:inline-flex;align-items:center;justify-content:center;width:' + size + 'px;height:' + size + 'px;background:' + bg + ';border-radius:' + br + 'px;font-size:' + fs + 'px;font-weight:700;color:' + fg + ';font-family:' + (ff || 'sans-serif') + ';letter-spacing:0;flex-shrink:0;">' + label + '</span>';
}

/**
 * Return an icon SVG for a file entry (replaces emoji-based getFileIcon).
 * Uses styled letter tags for Office/text/code files, SVG icons for other types.
 * @param {object} entry - file entry with .name, .is_dir, .category
 * @param {number} [size=32] - icon size in px (gallery default 32, list 22)
 * @returns {string} HTML markup (SVG or styled span)
 */
function fileIconSVG(entry, size) {
  size = size || 32;

  if (!entry) return iconSVG('file', size);
  if (entry.is_dir) return iconSVG(entry.marker ? 'folder-project' : 'folder', size);

  var cat = entry.category;
  if (cat === 'image') return iconSVG('image', size);
  if (cat === 'video') return iconSVG('video', size);
  if (cat === 'audio') return iconSVG('music', size);

  // Detect extension for typed tags
  var name = entry.name || '';
  var ext = name.includes('.') ? name.split('.').pop().toLowerCase() : '';

  // Office file styled tags
  if (ext === 'doc' || ext === 'docx')  return _tag('W', '#2b5797', '#fff', size);
  if (ext === 'xls' || ext === 'xlsx' || ext === 'csv') return _tag('X', '#217346', '#fff', size);
  if (ext === 'ppt' || ext === 'pptx') return _tag('P', '#c43e1c', '#fff', size);

  if (ext === 'pdf') return iconSVG('file-text', size);

  // Text/Code file styled tags (high-frequency types)
  if (ext === 'md' || ext === 'markdown') return _tag('M', '#7b1fa2', '#fff', size);
  if (ext === 'py')                       return _tag('Py', '#306998', '#fff', size);
  if (ext === 'sh' || ext === 'bash')     return _tag('$', '#2e7d32', '#fff', size, 'monospace');
  if (ext === 'json')                     return _tag('{}', '#e65100', '#fff', size, 'monospace');
  if (ext === 'txt')                      return _tag('T', '#616161', '#fff', size);
  if (ext === 'js' || ext === 'ts')       return _tag('JS', '#e6a817', '#1a1a1a', size);

  // Generic code files
  var codeExts = ['html','css','scss','less','tsx','jsx','go','rs','rb','php','java','c','cpp','h','sql','yaml','yml','toml','xml'];
  if (codeExts.indexOf(ext) !== -1) return iconSVG('file-code', size);

  // Archives
  var archiveExts = ['zip','tar','gz','7z','rar','bz2'];
  if (archiveExts.indexOf(ext) !== -1) return iconSVG('archive', size);

  // Default
  return iconSVG('file', size);
}

/**
 * Gallery thumb wrapper — larger container for card view.
 * @param {object} entry
 * @returns {string} HTML string
 */
function fileThumbSVG(entry) {
  var svg = fileIconSVG(entry, 32);
  return '<span style="display:inline-flex;align-items:center;justify-content:center;width:56px;height:56px;font-size:48px;flex-shrink:0;">' + svg + '</span>';
}
