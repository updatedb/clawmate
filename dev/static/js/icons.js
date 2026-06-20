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
  'file':          '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/>',
  'file-text':     '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
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
 * Return an icon SVG for a file entry (replaces emoji-based getFileIcon).
 * Uses styled letter tags for Office files, SVG icons for other types.
 * @param {object} entry - file entry with .name, .is_dir, .category
 * @returns {string} HTML markup (SVG or styled span)
 */
function fileIconSVG(entry) {
  if (!entry) return iconSVG('file', 18);
  if (entry.is_dir) return iconSVG('folder', 18);

  var cat = entry.category;
  if (cat === 'image') return iconSVG('image', 18);
  if (cat === 'video') return iconSVG('video', 18);
  if (cat === 'audio') return iconSVG('music', 18);

  // Detect extension for Office files and special types
  var name = entry.name || '';
  var ext = name.includes('.') ? name.split('.').pop().toLowerCase() : '';

  // Office file styled tags
  if (ext === 'doc' || ext === 'docx') {
    return '<span style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;background:#2b5797;border-radius:6px;font-size:11px;font-weight:700;color:#fff;font-family:sans-serif;letter-spacing:0;flex-shrink:0;">W</span>';
  }
  if (ext === 'xls' || ext === 'xlsx' || ext === 'csv') {
    return '<span style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;background:#217346;border-radius:6px;font-size:11px;font-weight:700;color:#fff;font-family:sans-serif;letter-spacing:0;flex-shrink:0;">X</span>';
  }
  if (ext === 'ppt' || ext === 'pptx') {
    return '<span style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;background:#c43e1c;border-radius:6px;font-size:11px;font-weight:700;color:#fff;font-family:sans-serif;letter-spacing:0;flex-shrink:0;">P</span>';
  }
  if (ext === 'pdf') return iconSVG('file-text', 18);
  if (ext === 'md' || ext === 'markdown') return iconSVG('file-text', 18);

  // Code files
  var codeExts = ['py','js','ts','tsx','jsx','html','css','scss','less','sh','bash','go','rs','rb','php','java','c','cpp','h','sql','json','yaml','yml','toml','xml'];
  if (codeExts.indexOf(ext) !== -1) return iconSVG('file', 18);

  // Archives
  var archiveExts = ['zip','tar','gz','7z','rar','bz2'];
  if (archiveExts.indexOf(ext) !== -1) return iconSVG('archive', 18);

  // Default
  return iconSVG('file', 18);
}

/**
 * Return an icon SVG element for use in list/gallery thumb areas.
 * Wraps the icon in a 32x32 centered container to match layout expectations.
 * @param {object} entry
 * @returns {string} HTML string
 */
function fileThumbSVG(entry) {
  var svg = fileIconSVG(entry);
  return '<span style="display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;font-size:18px;flex-shrink:0;">' + svg + '</span>';
}
