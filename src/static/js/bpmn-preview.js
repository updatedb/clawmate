/**
 * ClawMate BPMN Preview — local BPMN 2.0 viewer, editor and export helpers.
 * bpmn-js is loaded only when a .bpmn file or a Markdown bpmn block is present.
 */
(function() {
  'use strict';

  var VIEWER_SCRIPT = './vendor/bpmn-js/bpmn-navigated-viewer.production.min.js';
  var MODELER_SCRIPT = './vendor/bpmn-js/bpmn-modeler.production.min.js';
  var viewerReady = null;
  var modelerReady = null;
  var ViewerConstructor = null;
  var ModelerConstructor = null;

  function escHtml(value) {
    return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function loadStyleOnce(id, href) {
    if (document.getElementById(id)) return;
    var link = document.createElement('link');
    link.id = id;
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }

  function loadScriptOnce(id, src) {
    var existing = document.getElementById(id);
    if (existing && existing._loadPromise) return existing._loadPromise;
    var script = existing || document.createElement('script');
    script.id = id;
    script.src = src;
    script._loadPromise = new Promise(function(resolve, reject) {
      script.onload = resolve;
      script.onerror = function() { reject(new Error('BPMN 组件加载失败')); };
    });
    if (!existing) document.head.appendChild(script);
    return script._loadPromise;
  }

  function ensureStyles() {
    loadStyleOnce('bpmn-diagram-js-css', './vendor/bpmn-js/diagram-js.css');
    loadStyleOnce('bpmn-js-css', './vendor/bpmn-js/bpmn-js.css');
    loadStyleOnce('bpmn-font-css', './vendor/bpmn-js/bpmn-font/css/bpmn.css');
  }

  function ensureViewer() {
    ensureStyles();
    if (!viewerReady) viewerReady = loadScriptOnce('bpmn-viewer-script', VIEWER_SCRIPT).then(function() {
      ViewerConstructor = window.BpmnJS;
    });
    return viewerReady;
  }

  function ensureModeler() {
    ensureStyles();
    if (!modelerReady) modelerReady = loadScriptOnce('bpmn-modeler-script', MODELER_SCRIPT).then(function() {
      ModelerConstructor = window.BpmnJS;
    });
    return modelerReady;
  }

  function downloadBlob(blob, fileName) {
    var url = URL.createObjectURL(blob);
    var link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function() { URL.revokeObjectURL(url); }, 0);
  }

  function svgStringToPng(svgText, fileName) {
    var svgUrl = URL.createObjectURL(new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' }));
    var image = new Image();
    image.onload = function() {
      var svg = new DOMParser().parseFromString(svgText, 'image/svg+xml').documentElement;
      var viewBox = (svg.getAttribute('viewBox') || '').trim().split(/\s+/);
      var width = Math.ceil(parseFloat(viewBox[2]) || parseFloat(svg.getAttribute('width')) || image.width || 1);
      var height = Math.ceil(parseFloat(viewBox[3]) || parseFloat(svg.getAttribute('height')) || image.height || 1);
      var canvas = document.createElement('canvas');
      var pixelRatio = 2;
      canvas.width = width * pixelRatio;
      canvas.height = height * pixelRatio;
      var context = canvas.getContext('2d');
      if (!context) {
        URL.revokeObjectURL(svgUrl);
        return;
      }
      context.scale(pixelRatio, pixelRatio);
      context.drawImage(image, 0, 0, width, height);
      URL.revokeObjectURL(svgUrl);
      try {
        canvas.toBlob(function(blob) {
          if (blob) downloadBlob(blob, fileName);
        }, 'image/png');
      } catch (_) {}
    };
    image.onerror = function() { URL.revokeObjectURL(svgUrl); };
    image.src = svgUrl;
  }

  async function createViewer(canvasElement, xml) {
    await ensureViewer();
    var viewer = new ViewerConstructor({ container: canvasElement });
    await viewer.importXML(xml);
    fitViewer(viewer);
    return viewer;
  }

  function fitViewer(viewer) {
    var canvas = viewer.get('canvas');
    canvas.resized();
    canvas.zoom('fit-viewport');
    requestAnimationFrame(function() {
      canvas.resized();
      canvas.zoom('fit-viewport');
      centerViewerViewport(viewer);
    });
  }

  function centerViewerViewport(viewer) {
    var container = viewer.get('canvas').getContainer();
    var viewport = container && container.querySelector('.viewport');
    if (!viewport) return;
    var bounds = viewport.getBBox();
    var rect = container.getBoundingClientRect();
    var scale = viewer.get('canvas').zoom() || 1;
    var x = (rect.width - bounds.width * scale) / 2 - bounds.x * scale;
    var y = (rect.height - bounds.height * scale) / 2 - bounds.y * scale;
    viewport.setAttribute('transform', 'matrix(' + scale + ' 0 0 ' + scale + ' ' + x + ' ' + y + ')');
  }

  function applyCurrentThemeToSvg(svgText) {
    var root = document.documentElement;
    var dark = root.getAttribute('data-theme') === 'dark' || document.body.getAttribute('data-theme') === 'dark';
    var background = dark ? '#0b1220' : '#ffffff';
    var themeCss = dark
      ? '.djs-shape .djs-visual > rect:first-child,.djs-shape .djs-visual > circle:first-child,.djs-shape .djs-visual > ellipse:first-child,.djs-shape .djs-visual > path:first-child,.djs-shape .djs-visual > polygon:first-child{fill:#1e293b!important;stroke:#dbeafe!important}.djs-connection .djs-visual>path{stroke:#cbd5e1!important}.djs-connection marker path{fill:#cbd5e1!important;stroke:#cbd5e1!important}.djs-shape .djs-visual>path:not(:first-child){fill:#dbeafe!important;stroke:#dbeafe!important}.djs-label,.djs-label tspan{fill:#f8fafc!important}'
      : '';
    return svgText.replace(/<svg([^>]*)>/i, '<svg$1><style>' + themeCss + '</style><rect data-bpmn-export-background="true" width="100%" height="100%" fill="' + background + '"/>');
  }

  async function exportPng(viewer, fileName) {
    var result = await viewer.saveSVG();
    svgStringToPng(applyCurrentThemeToSvg(result.svg), fileName + '.png');
  }

  function createToolbar(fileName, includeEditor, includePngExport, includeExpand) {
    return '<div class="bpmn-toolbar" aria-label="BPMN 图表工具">' +
      '<button type="button" class="bpmn-tool-btn" data-bpmn-action="zoom-out" title="缩小">−</button>' +
      '<button type="button" class="bpmn-tool-btn" data-bpmn-action="fit" title="适配画布">⊙</button>' +
      '<button type="button" class="bpmn-tool-btn" data-bpmn-action="zoom-in" title="放大">+</button>' +
      (includePngExport ? '<button type="button" class="bpmn-tool-btn" data-bpmn-action="png" title="导出 PNG">⇩</button>' : '') +
      (includeExpand ? '<button type="button" class="bpmn-tool-btn" data-bpmn-action="expand" title="展开图表">□</button>' : '') +
      (includeEditor ? '<button type="button" class="bpmn-tool-btn bpmn-edit-btn" data-bpmn-action="edit">编辑 BPMN</button>' : '') +
      '</div>';
  }

  function showError(container, xml, error) {
    container.innerHTML = '<div class="bpmn-error"><strong>⚠️ BPMN 渲染失败</strong><p>' +
      escHtml(error && (error.message || String(error))) + '</p><pre>' + escHtml(xml) + '</pre></div>';
  }

  function closeFailedOverlay(overlay, instance) {
    if (instance) instance.destroy();
    overlay.remove();
    document.body.style.overflow = '';
  }

  function showDialogError(overlay, dialog, xml, error, instance) {
    showError(dialog, xml, error);
    dialog.insertAdjacentHTML('beforeend', '<div class="bpmn-expand-header"><span>无法打开 BPMN</span><button type="button" class="bpmn-expand-close" aria-label="Close">×</button></div>');
    overlay.addEventListener('click', function(event) {
      if (event.target === overlay || event.target.closest('.bpmn-expand-close')) {
        closeFailedOverlay(overlay, instance);
      }
    });
  }

  function installToolbar(container, viewer, fileName, options) {
    container.insertAdjacentHTML('beforeend', createToolbar(fileName, !!options.editable, options.pngExport !== false, !!options.expand));
    container.querySelector('.bpmn-toolbar').addEventListener('click', function(event) {
      var button = event.target.closest('[data-bpmn-action]');
      if (!button) return;
      var action = button.dataset.bpmnAction;
      if (action === 'zoom-out') zoomViewer(viewer, -0.1);
      else if (action === 'fit') fitViewer(viewer);
      else if (action === 'zoom-in') zoomViewer(viewer, 0.1);
      else if (action === 'png') exportPng(viewer, fileName);
      else if (action === 'expand') openBpmnExpandDialog(options.xml, options.title || fileName, options);
      else if (action === 'edit' && options.onEdit) options.onEdit(container);
      else if (action === 'edit') openEditor(options);
    });
  }

  function zoomViewer(viewer, delta) {
    var canvas = viewer.get('canvas');
    var currentZoom = canvas.zoom();
    canvas.zoom(Math.max(0.3, Math.min(5, currentZoom + delta)));
    requestAnimationFrame(function() { centerViewerViewport(viewer); });
  }

  function setupBpmnResizeHandle(container) {
    if (!container.classList.contains('bpmn-diagram') || container.querySelector('.bpmn-resize-handle')) return;
    var handle = document.createElement('div');
    handle.className = 'bpmn-resize-handle';
    handle.style.touchAction = 'none';
    container.appendChild(handle);
    var dragging = false, startY, startHeight, pointerId;
    handle.addEventListener('pointerdown', function(event) {
      dragging = true;
      pointerId = event.pointerId;
      startY = event.clientY;
      startHeight = container.getBoundingClientRect().height;
      handle.classList.add('dragging');
      handle.setPointerCapture(pointerId);
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'ns-resize';
      event.preventDefault();
    });
    handle.addEventListener('pointermove', function(event) {
      if (!dragging) return;
      var height = Math.max(100, Math.min(window.innerHeight * 0.9, startHeight + event.clientY - startY));
      container.style.height = height + 'px';
    });
    function stopResize() {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove('dragging');
      handle.releasePointerCapture(pointerId);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    }
    handle.addEventListener('pointerup', stopResize);
    handle.addEventListener('pointercancel', stopResize);
  }

  async function openBpmnExpandDialog(xml, title, options) {
    options = options || {};
    var existing = document.querySelector('.mermaid-expand-overlay');
    if (existing) {
      existing.remove();
      document.body.style.overflow = '';
    }
    var overlay = document.createElement('div');
    overlay.className = 'mermaid-expand-overlay';
    overlay.innerHTML = '<div class="mermaid-expand-dialog"><div class="mermaid-expand-header"><span class="mermaid-expand-title">' + escHtml(title) +
      '</span><div class="mermaid-expand-actions"></div></div><div class="mermaid-expand-body"><div class="bpmn-modal-canvas"></div></div></div>';
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(function() { overlay.classList.add('active'); });
    var canvas = overlay.querySelector('.bpmn-modal-canvas');
    var actions = overlay.querySelector('.mermaid-expand-actions');
    var instance = null;
    var editing = false;

    function close() {
      if (instance) instance.destroy();
      document.body.style.overflow = '';
      overlay.remove();
    }
    function renderViewerActions() {
      actions.innerHTML = '<div class="mermaid-zoom-controls" style="position:static;display:flex;background:transparent;backdrop-filter:none;padding:0;">' +
        '<button class="mermaid-zoom-btn" data-bpmn-expand="out" title="缩小">−</button>' +
        '<button class="mermaid-zoom-btn" data-bpmn-expand="fit" title="适配画布">⊙</button>' +
        '<button class="mermaid-zoom-btn" data-bpmn-expand="in" title="放大">+</button>' +
        '<button class="mermaid-zoom-btn" data-bpmn-expand="png" title="导出 PNG">⇩</button></div>' +
        (options.onSaveXml ? '<button type="button" class="mermaid-zoom-btn" data-bpmn-expand="edit" aria-label="编辑 BPMN" title="编辑 BPMN">✎</button>' : '') +
        '<button class="mermaid-expand-close" aria-label="Close">×</button>';
    }
    function renderEditorActions() {
      actions.innerHTML = '<button type="button" class="mermaid-zoom-btn" data-bpmn-expand="save" aria-label="保存 BPMN" title="保存 BPMN">💾</button>' +
        '<button class="mermaid-expand-close" aria-label="Close">×</button>';
    }
    async function renderViewer() {
      if (instance) instance.destroy();
      canvas.innerHTML = '';
      instance = await createViewer(canvas, xml);
      editing = false;
      renderViewerActions();
    }
    async function renderModalEditor() {
      if (instance) instance.destroy();
      canvas.innerHTML = '';
      await ensureModeler();
      instance = new ModelerConstructor({ container: canvas });
      await instance.importXML(xml);
      fitViewer(instance);
      editing = true;
      renderEditorActions();
    }
    try {
      await renderViewer();
    } catch (error) {
      showError(overlay.querySelector('.mermaid-expand-dialog'), xml, error);
      return;
    }
    overlay.addEventListener('click', function(event) {
      if (event.target === overlay || event.target.closest('.mermaid-expand-close')) return close();
      var action = event.target.dataset && event.target.dataset.bpmnExpand;
      if (!action) return;
      if (action === 'out') zoomViewer(instance, -0.1);
      else if (action === 'fit') fitViewer(instance);
      else if (action === 'in') zoomViewer(instance, 0.1);
      else if (action === 'png') exportPng(instance, options.pngFileName || 'bpmn-diagram');
      else if (action === 'edit' && !editing) {
        renderModalEditor().catch(function(error) { showError(canvas, xml, error); });
      } else if (action === 'save' && editing) {
        (async function() {
          try {
            var saved = await instance.saveXML({ format: true });
            await options.onSaveXml(saved.xml);
            xml = saved.xml;
            await renderViewer();
          } catch (error) {
            window.alert('保存失败：' + (error.message || error));
          }
        })();
      }
    });
  }

  async function saveBpmn(root, path, modeler) {
    var saved = await modeler.saveXML({ format: true });
    var response = await fetch('/api/clawmate/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ root: root, path: path, content: saved.xml })
    });
    var data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.detail || '保存 BPMN 失败');
    return saved.xml;
  }

  async function openEditor(options) {
    var existing = document.querySelector('.bpmn-editor-overlay');
    if (existing) existing.remove();
    var overlay = document.createElement('div');
    overlay.className = 'bpmn-editor-overlay';
    overlay.innerHTML = '<div class="bpmn-editor-dialog"><div class="bpmn-expand-header"><span>编辑 BPMN：' + escHtml(options.fileName) +
      '</span><div><button type="button" class="bpmn-save-btn">保存</button><button type="button" class="bpmn-expand-close" aria-label="Close">×</button></div></div><div class="bpmn-editor-canvas"></div><div class="bpmn-editor-status" aria-live="polite"></div></div>';
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(function() { overlay.classList.add('active'); });
    var modeler;
    try {
      await ensureModeler();
      modeler = new ModelerConstructor({ container: overlay.querySelector('.bpmn-editor-canvas') });
      await modeler.importXML(options.xml);
      modeler.get('canvas').zoom('fit-viewport');
    } catch (error) {
      showDialogError(overlay, overlay.querySelector('.bpmn-editor-dialog'), options.xml, error, modeler);
      return;
    }
    function close() {
      modeler.destroy();
      overlay.remove();
      document.body.style.overflow = '';
    }
    overlay.addEventListener('click', async function(event) {
      if (event.target === overlay || event.target.closest('.bpmn-expand-close')) {
        close();
        return;
      }
      if (!event.target.closest('.bpmn-save-btn')) return;
      var status = overlay.querySelector('.bpmn-editor-status');
      status.textContent = '保存中…';
      try {
        var xml = await saveBpmn(options.root, options.path, modeler);
        status.textContent = '已保存';
        options.onSaved(xml);
        close();
      } catch (error) {
        status.textContent = '保存失败：' + (error.message || error);
      }
    });
  }

  async function openInlineEditor(container, options) {
    container.innerHTML = '<div class="bpmn-editor-canvas bpmn-inline-editor"></div>';
    var modeler;
    var dirty = false;
    function notify() {
      if (options.onEditingChange) options.onEditingChange({ dirty: dirty, save: save, cancel: cancel });
    }
    function cancel() {
      if (modeler) modeler.destroy();
      if (options.onCancelled) options.onCancelled();
    }
    async function save() {
      try {
        var xml;
        if (options.saveXml) {
          var saved = await modeler.saveXML({ format: true });
          xml = await options.saveXml(saved.xml);
        } else {
          xml = await saveBpmn(options.root, options.path, modeler);
        }
        if (options.onSaved) options.onSaved(xml);
      } catch (error) {
        if (options.onSaveError) options.onSaveError(error);
      }
    }
    try {
      await ensureModeler();
      modeler = new ModelerConstructor({ container: container.querySelector('.bpmn-inline-editor') });
      await modeler.importXML(options.xml);
      fitViewer(modeler);
      modeler.on('commandStack.changed', function() {
        dirty = true;
        notify();
      });
      notify();
      return modeler;
    } catch (error) {
      showError(container, options.xml, error);
      if (options.onSaveError) options.onSaveError(error);
      return null;
    }
  }

  async function renderEmbedded(container, xml, options) {
    try {
      var viewer = await createViewer(container.querySelector('.bpmn-canvas'), xml);
      installToolbar(container, viewer, 'bpmn-diagram', Object.assign({ xml: xml, editable: false, expand: true, pngExport: false }, options || {}));
      setupBpmnResizeHandle(container);
      return viewer;
    } catch (error) {
      showError(container, xml, error);
      return null;
    }
  }

  async function renderFile(container, options) {
    try {
      var viewer = await createViewer(container.querySelector('.bpmn-canvas'), options.xml);
      installToolbar(container, viewer, options.fileName, Object.assign({}, options, { fullscreen: false, pngExport: false }));
      return viewer;
    } catch (error) {
      showError(container, options.xml, error);
      return null;
    }
  }

  window.BpmnPreview = {
    ensureViewer: ensureViewer,
    renderEmbedded: renderEmbedded,
    renderFile: renderFile,
    exportPng: exportPng,
    openEditor: openEditor,
    openInlineEditor: openInlineEditor
  };
})();
