/* Controlled generated-image panel. All image files stay as project paths. */
(function (global) {
  'use strict';
  var mounted;
  function esc(value) { var d = document.createElement('div'); d.textContent = String(value || ''); return d.innerHTML; }
  function endpoint(context) { return '/api/clawmate/generated-assets/' + encodeURIComponent(context.root) + '/' + encodeURIComponent(context.project); }
  function mount(options) {
    if (mounted) return mounted;
    var panel = document.getElementById('previewImageAssetsPanel');
    var form = document.getElementById('previewImageAssetsForm');
    var prompt = document.getElementById('previewImageAssetsPrompt');
    var purpose = document.getElementById('previewImageAssetsPurpose');
    var topic = document.getElementById('previewImageAssetsTopic');
    var count = document.getElementById('previewImageAssetsCount');
    var status = document.getElementById('previewImageAssetsStatus');
    var candidates = document.getElementById('previewImageAssetsCandidates');
    var sourcePrompt = document.getElementById('previewImageAssetsSourcePrompt');
    function context() { return options.getContext(); }
    function render(data) {
      candidates.innerHTML = (data.candidates || []).map(function (item) {
        var url = '/api/clawmate/preview?root=' + encodeURIComponent(context().root) + '&path=' + encodeURIComponent(item.path);
        return '<article class="image-assets-candidate"><img src="' + url + '" alt="候选图"><div><b>候选 ' + esc(item.id) + '</b><p>' + esc(item.summary) + '</p><button type="button" data-adopt="' + esc(item.id) + '">采用</button></div></article>';
      }).join('');
      candidates.querySelectorAll('[data-adopt]').forEach(function (button) {
        button.onclick = async function () {
          button.disabled = true;
          var response = await fetch(endpoint(context()) + '/tasks/' + encodeURIComponent(data.task.id) + '/adopt', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({candidate_id:button.getAttribute('data-adopt')})});
          if (response.ok) { status.textContent = '已采用；文件已保存，目录变更请手动刷新查看。'; }
          else { status.textContent = '采用失败'; button.disabled = false; }
        };
      });
    }
    async function refreshPrompt() {
      var c = context();
      var response = await fetch(endpoint(c) + '/source-prompt?path=' + encodeURIComponent(c.file));
      var data = response.ok ? await response.json() : {};
      sourcePrompt.textContent = data.recorded ? data.prompt : '未记录';
    }
    form.addEventListener('submit', async function (event) {
      event.preventDefault();
      var c = context();
      var amount = Math.max(1, Math.min(4, Number(count.value) || 1));
      count.value = String(amount);
      status.textContent = '正在提交生成任务…';
      var response = await fetch(endpoint(c) + '/tasks', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source_path:c.file, prompt:prompt.value, purpose:purpose.value, topic:topic.value, width:1024, height:1024, candidate_count:amount})});
      var data = await response.json();
      if (!response.ok) { status.textContent = data.detail || '任务提交失败'; return; }
      status.textContent = '任务已交给后台 Agent；完成后点击刷新候选。';
      panel.dataset.taskId = data.task.id;
    });
    document.getElementById('previewImageAssetsClose').onclick = function () { mounted.close(); };
    mounted = {
      open: function () { panel.classList.remove('hidden'); refreshPrompt(); return mounted; },
      close: function () { panel.classList.add('hidden'); options.onClose(); },
      refresh: async function () { if (!panel.dataset.taskId) return; var response = await fetch(endpoint(context()) + '/tasks/' + encodeURIComponent(panel.dataset.taskId)); if (response.ok) render(await response.json()); },
      isOpen: function () { return !panel.classList.contains('hidden'); }
    };
    return mounted;
  }
  global.ClawMateImageAssetsPanel = {mount: mount};
})(window);
