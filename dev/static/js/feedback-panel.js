/**
 * Shared feedback/review panel primitives.
 *
 * This file deliberately owns the feedback-card DOM contract, while callers
 * own their containers, storage and endpoint capability (share token vs.
 * preview project APIs).  Positioning/action filtering delegate to
 * preview-common.js, which remains the single source of locator rules.
 */
(function(global) {
  'use strict';

  function position(item) {
    return String(item && (item.position || item.location) || '').trim();
  }
  function time(item) {
    var value = String(item && (item.updated || item.created) || '');
    var match = value.match(/(?:^\d{4}-)?(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})/);
    return match ? match[1] + '-' + match[2] + ' ' + match[3] + ':' + match[4] : value;
  }
  function actions(templates, file) {
    return global.getSelectionActionTemplates ? global.getSelectionActionTemplates(templates, file) : [];
  }
  function selectionPosition(options) {
    return global.getFeedbackSelectionPosition ? global.getFeedbackSelectionPosition(options) : {position: ''};
  }
  function submissionPayload(items, author) {
    return {author: author || '', selections: (items || []).map(function(item) {
      return {text: item.text || item.content || '', note: item.note || '', action: item.action || '',
        scope: item.scope || 'document', task_id: item.task_id || '', position: position(item)};
    })};
  }
  // Shared required-field rule for a submission/draft item set. Returns the
  // first missing-field message (「请填写选中内容」/「请填写建议」/「请选择操作类型」)
  // or null when every item is complete. Callers whose card path supplies an
  // action default (pending cards) pass requireAction:false so they don't force
  // the user to pick one; the share/review 浮窗 both reuse this rule.
  function validateSubmission(items, options) {
    options = options || {};
    var requireAction = options.requireAction !== false;
    items = (items || []).slice();
    if (!items.length) return null;
    for (var i = 0; i < items.length; i++) {
      var item = items[i] || {};
      if (!String(item.text || item.content || '').trim()) return '请填写选中内容';
      if (!String(item.note || '').trim()) return '请填写建议';
      if (requireAction && !String(item.action || '').trim()) return '请选择操作类型';
    }
    return null;
  }
  function stop(event) { if (event) event.stopPropagation(); }
  function editableText(item, key, placeholder, rows, persist) {
    var input = document.createElement('textarea');
    input.className = 'fb-note-input'; input.value = item[key] || ''; input.rows = rows;
    input.placeholder = placeholder; input.setAttribute('aria-label', placeholder.replace(/（必填）.*/, '（可编辑）'));
    input.addEventListener('input', function() { item[key] = input.value; persist(); });
    input.addEventListener('click', stop); return input;
  }

  // Creates both editable pending and read-only submitted/review cards. Page
  // adapters supply mutation and action callbacks, so token/project context
  // can never leak across surfaces.
  function buildCard(options) {
    var item = options.item, readOnly = !!options.readOnly, persist = options.persist || function() {};
    var card = document.createElement(options.tagName || 'div');
    card.className = 'fb-card' + (readOnly ? ' fb-card-completed' : '') + (options.selected ? ' selected' : '');
    if (item.id) card.dataset.id = item.id;
    var head = document.createElement('div'); head.className = 'fb-card-header';
    var id = document.createElement('span'); id.className = 'fb-card-id'; id.textContent = item.id || '';
    var stamp = document.createElement('span'); stamp.className = 'fb-card-time fb-card-stage-time'; stamp.textContent = time(item);
    var status = document.createElement('span'); status.className = 'fb-status-pill ' + (item.status || (readOnly ? 'pending_review' : 'pending'));
    status.textContent = options.statusLabel ? options.statusLabel(item.status, readOnly) : (readOnly ? (item.status || '已提交') : '待提交');
    head.appendChild(id); head.appendChild(stamp); head.appendChild(status);
    if (options.onDelete) { var del = document.createElement('button'); del.className='fb-btn-delete'; del.textContent='✕'; del.title=options.deleteTitle || '删除'; del.addEventListener('click', function(e){ stop(e); options.onDelete(item); }); head.appendChild(del); }
    card.appendChild(head);
    if (readOnly) {
      var meta = document.createElement('div'); meta.className = 'fb-card-meta';
      if (options.actionLabel) { var action = document.createElement('span'); action.className='fb-card-action'; action.textContent=options.actionLabel(item.action) || '—'; meta.appendChild(action); }
      var roPos = document.createElement('div'); roPos.className='fb-card-position'; roPos.textContent='定位：' + (position(item) || '—'); meta.appendChild(roPos); card.appendChild(meta);
      var text = document.createElement('div'); text.className='review-card-content'; text.textContent=item.text || item.content || '（未填写选中内容）'; card.appendChild(text);
      var note = document.createElement('div'); note.className='fb-card-note'; note.textContent='建议：' + (item.note || '—'); card.appendChild(note);
    } else {
      var pos = document.createElement('input'); pos.type='text'; pos.className='fb-card-position-edit'; pos.value=position(item); pos.placeholder=options.positionPlaceholder || '定位：—（Line {start}-{end}）'; pos.title='定位（可编辑）'; pos.setAttribute('aria-label','定位（可编辑）');
      pos.addEventListener('input', function(){ item.position=pos.value; persist(); }); pos.addEventListener('click', stop); card.appendChild(pos);
      card.appendChild(editableText(item, options.textKey || 'text', options.textPlaceholder || '原文（必填）', 2, persist));
      card.appendChild(editableText(item, 'note', options.notePlaceholder || '反馈（必填）：简要说明改动需求', 3, persist));
      var available = actions(options.templates, options.file);
      if (available.length) { var tags=document.createElement('div'); tags.className='pst-tags'; tags.style.cssText='display:flex;gap:4px;flex-wrap:wrap;margin-top:4px;'; available.forEach(function(template) { var button=document.createElement('button'); button.className='pst-tag' + (item.action === template.action ? ' active' : ''); button.textContent=template.label; button.addEventListener('click', function(e){ stop(e); item.action=template.action; item.scope=template.scope; item.task_id=template.id; persist(); if (options.onAction) options.onAction(item); }); tags.appendChild(button); }); card.appendChild(tags); }
    }
    if (options.buttons) { var buttons=document.createElement('div'); buttons.className='fb-card-actions'; options.buttons(item, buttons, readOnly); if (buttons.childElementCount) card.appendChild(buttons); }
    return card;
  }

  global.ClawMateFeedbackPanel = {position: position, time: time, actions: actions, selectionPosition: selectionPosition, submissionPayload: submissionPayload, validateSubmission: validateSubmission, buildCard: buildCard};
})(window);
