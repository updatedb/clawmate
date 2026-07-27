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
    viewer.get('canvas').zoom('fit-viewport');
    return viewer;
  }

  async function exportSvg(viewer, fileName) {
    var result = await viewer.saveSVG();
    downloadBlob(new Blob([result.svg], { type: 'image/svg+xml;charset=utf-8' }), fileName + '.svg');
  }

  async function exportPng(viewer, fileName) {
    var result = await viewer.saveSVG();
    svgStringToPng(result.svg, fileName + '.png');
  }

  function createToolbar(fileName, includeEditor) {
    return '<div class="bpmn-toolbar" aria-label="BPMN 图表工具">' +
      '<button type="button" class="bpmn-tool-btn" data-bpmn-action="fit" title="适配画布">⊙</button>' +
      '<button type="button" class="bpmn-tool-btn" data-bpmn-action="fullscreen" title="全屏查看">□</button>' +
      '<button type="button" class="bpmn-tool-btn" data-bpmn-action="svg" title="导出 SVG">SVG</button>' +
      '<button type="button" class="bpmn-tool-btn" data-bpmn-action="png" title="导出 PNG">⇩</button>' +
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
    container.insertAdjacentHTML('beforeend', createToolbar(fileName, !!options.editable));
    container.querySelector('.bpmn-toolbar').addEventListener('click', function(event) {
      var button = event.target.closest('[data-bpmn-action]');
      if (!button) return;
      var action = button.dataset.bpmnAction;
      if (action === 'fit') viewer.get('canvas').zoom('fit-viewport');
      else if (action === 'fullscreen') openViewerDialog(options.xml, fileName);
      else if (action === 'svg') exportSvg(viewer, fileName);
      else if (action === 'png') exportPng(viewer, fileName);
      else if (action === 'edit') openEditor(options);
    });
  }

  async function openViewerDialog(xml, fileName) {
    var existing = document.querySelector('.bpmn-expand-overlay');
    if (existing) existing.remove();
    var overlay = document.createElement('div');
    overlay.className = 'bpmn-expand-overlay';
    overlay.innerHTML = '<div class="bpmn-expand-dialog"><div class="bpmn-expand-header"><span>' + escHtml(fileName) +
      '</span><div><button type="button" class="bpmn-tool-btn" data-dialog-action="fit">⊙</button><button type="button" class="bpmn-tool-btn" data-dialog-action="png">⇩</button><button type="button" class="bpmn-expand-close" aria-label="Close">×</button></div></div><div class="bpmn-canvas bpmn-dialog-canvas"></div></div>';
    document.body.appendChild(overlay);
    document.body.style.overflow = 'hidden';
    var viewer;
    try {
      viewer = await createViewer(overlay.querySelector('.bpmn-dialog-canvas'), xml);
    } catch (error) {
      showDialogError(overlay, overlay.querySelector('.bpmn-expand-dialog'), xml, error, viewer);
      return;
    }
    function close() {
      viewer.destroy();
      overlay.remove();
      document.body.style.overflow = '';
    }
    overlay.addEventListener('click', function(event) {
      if (event.target === overlay || event.target.closest('.bpmn-expand-close')) close();
      var action = event.target.dataset && event.target.dataset.dialogAction;
      if (action === 'fit') viewer.get('canvas').zoom('fit-viewport');
      if (action === 'png') exportPng(viewer, fileName);
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

  async function renderEmbedded(container, xml) {
    try {
      var viewer = await createViewer(container.querySelector('.bpmn-canvas'), xml);
      installToolbar(container, viewer, 'bpmn-diagram', { xml: xml, editable: false });
      return viewer;
    } catch (error) {
      showError(container, xml, error);
      return null;
    }
  }

  async function renderFile(container, options) {
    try {
      var viewer = await createViewer(container.querySelector('.bpmn-canvas'), options.xml);
      installToolbar(container, viewer, options.fileName, Object.assign({}, options, { editable: true }));
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
    openEditor: openEditor
  };
})();
