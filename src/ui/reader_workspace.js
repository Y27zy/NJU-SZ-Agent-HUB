export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const app = parentElement.closest?.('.stApp') || parentElement.getRootNode()?.host?.closest?.('.stApp');
  app?.classList.add('workspace-component-ready');

  const root = parentElement.querySelector('#study-workspace');
  const side = parentElement.querySelector('#study-sidebar');
  const reader = parentElement.querySelector('#study-reader');
  const canvas = parentElement.querySelector('#study-canvas');
  const sidebarResizer = parentElement.querySelector('#sidebar-resizer');
  const resizer = parentElement.querySelector('#reader-resizer');
  const menu = parentElement.querySelector('#selection-menu');
  const modelMenu = parentElement.querySelector('#model-menu');
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);

  const userId = Number(data?.userId || 0);
  const documentId = Number(data?.documentId || 0);
  const apiBase = String(data?.apiBase || '');
  const apiToken = String(data?.apiToken || '');
  const api = async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'X-Reader-Token': apiToken,
        ...(options.headers || {})
      }
    });
    const payload = await response.json().catch(() => ({ ok: false, error: `HTTP ${response.status}` }));
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  };
  const requestBody = (extra = {}) => JSON.stringify({ user_id: userId, document_id: documentId, ...extra });

  let nodes = [...(data?.nodes || [])];
  let highlights = [...(data?.highlights || [])];
  let selected = null;
  let dragState = null;
  let nodeResizeState = null;
  let resizingSidebar = false;
  let resizingReader = false;
  let canvasPan = null;
  const hiddenNodes = new Set();
  const jobs = new Map();
  const readerStateKey = `nju-reader-scroll-${documentId}`;
  const canvasStateKey = `nju-canvas-scroll-${documentId}`;
  const contextKey = `nju-reader-context-${documentId}`;
  const learningKey = `nju-reader-learning-prompt-${documentId}`;
  const widthKey = `nju-reader-width-${documentId}`;
  const sidebarWidthKey = `nju-sidebar-width-${documentId}`;
  let contextMode = localStorage.getItem(contextKey) || data?.contextMode || 'section';
  let learningPrompt = localStorage.getItem(learningKey) || '';

  const renderMath = (scope) => scope.querySelectorAll('.math-tex').forEach((element) => {
    const source = element.textContent || '';
    try {
      globalThis.katex.render(source, element, {
        displayMode: element.dataset.display === 'block',
        throwOnError: false,
        strict: 'ignore',
        trust: false,
        output: 'htmlAndMathml'
      });
    } catch (_error) {
      element.classList.add('katex-error');
      element.textContent = source;
    }
  });

  const toast = (message, kind = 'info') => {
    let element = root.querySelector('.reader-toast');
    if (!element) {
      element = document.createElement('div');
      element.className = 'reader-toast';
      root.appendChild(element);
    }
    element.className = `reader-toast is-${kind}`;
    element.textContent = message;
    element.hidden = false;
    clearTimeout(element.__timer);
    element.__timer = setTimeout(() => { element.hidden = true; }, 2600);
  };

  const visibleTextNodes = () => {
    const walker = document.createTreeWalker(reader, NodeFilter.SHOW_TEXT);
    const result = [];
    let offset = 0;
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement?.closest('script,style,.katex-mathml')) continue;
      result.push({ node, start: offset, end: offset + node.data.length });
      offset += node.data.length;
    }
    return result;
  };

  const rangeFromOffsets = (start, end) => {
    const parts = visibleTextNodes();
    const startPart = parts.find((item) => item.start <= start && item.end >= start);
    const endPart = parts.find((item) => item.start < end && item.end >= end);
    if (!startPart || !endPart) return null;
    const range = document.createRange();
    range.setStart(startPart.node, Math.max(0, start - startPart.start));
    range.setEnd(endPart.node, Math.max(0, end - endPart.start));
    return range;
  };

  const firstTextRange = (text) => {
    const wanted = String(text || '').trim();
    if (!wanted) return null;
    const parts = visibleTextNodes();
    const combined = parts.map((item) => item.node.data).join('');
    const start = combined.indexOf(wanted);
    return start >= 0 ? rangeFromOffsets(start, start + wanted.length) : null;
  };

  const selectionPayload = () => {
    const selection = parentElement.getSelection ? parentElement.getSelection() : window.getSelection();
    if (!selection || !selection.rangeCount || selection.isCollapsed) return null;
    const range = selection.getRangeAt(0);
    const readerSelection = reader.contains(range.commonAncestorContainer);
    const nodeElement = range.commonAncestorContainer.parentElement?.closest?.('.canvas-node');
    if (!readerSelection && !nodeElement) return null;
    const text = selection.toString().trim();
    if (!text) return null;
    const payload = {
      text,
      range: range.cloneRange(),
      rect: range.getBoundingClientRect(),
      sourceNodeId: nodeElement ? Number(nodeElement.dataset.nodeId || 0) : null,
      anchorStart: null,
      anchorEnd: null,
      contextPrefix: '',
      contextSuffix: ''
    };
    if (readerSelection) {
      const parts = visibleTextNodes();
      const startPart = parts.find((item) => item.node === range.startContainer);
      const endPart = parts.find((item) => item.node === range.endContainer);
      if (startPart && endPart) {
        payload.anchorStart = startPart.start + range.startOffset;
        payload.anchorEnd = endPart.start + range.endOffset;
        const combined = parts.map((item) => item.node.data).join('');
        payload.contextPrefix = combined.slice(Math.max(0, payload.anchorStart - 120), payload.anchorStart);
        payload.contextSuffix = combined.slice(payload.anchorEnd, payload.anchorEnd + 120);
      }
    }
    return payload;
  };

  const syncHighlights = () => {
    const ranges = [];
    for (const item of highlights) {
      const start = Number(item.anchor_start);
      const end = Number(item.anchor_end);
      const range = Number.isFinite(start) && Number.isFinite(end) && end > start
        ? rangeFromOffsets(start, end)
        : firstTextRange(item.selected_text || item.selectedText);
      if (range) ranges.push(range);
    }
    if (globalThis.CSS?.highlights && globalThis.Highlight) {
      CSS.highlights.set('nju-reader-marks', new Highlight(...ranges));
    }
  };

  const highlightIsSelected = () => selected && highlights.some((item) => (
    Number(item.anchor_start) === selected.anchorStart && Number(item.anchor_end) === selected.anchorEnd
  ));

  const renderSidebarHighlights = () => {
    const container = side.querySelector('.highlight-list');
    if (!container) return;
    container.innerHTML = highlights.length
      ? `<div class="section-label">我的重点 · ${highlights.length}</div>${highlights.map((item) => `
          <div class="highlight-row" data-highlight-anchor="${item.id}">
            <button class="section-button">${esc(String(item.selected_text || item.selectedText || '').replace(/\s+/g, ' ').slice(0, 34))}</button>
            <button class="highlight-delete" data-highlight-delete="${item.id}" title="删除标记">×</button>
          </div>`).join('')}`
      : '';
  };

  const renderSidebar = () => {
    const sections = data?.sections || [];
    const models = data?.models || [];
    side.innerHTML = `
      <div class="side-top">
        <button class="side-icon" data-command="collapse-side" title="收起目录">☰</button>
        <span class="side-brand">NJU Reader</span>
        <span class="workspace-badge">${esc(data?.mode || '学习')}</span>
        <button class="back-workspace" data-command="back" title="返回资料库">‹</button>
      </div>
      <div class="side-doc">${esc(data?.title || '资料')}</div>
      <nav class="section-list">
        <div class="section-label">章节目录 · ${sections.length}</div>
        ${sections.map((item, index) => `<button class="section-button ${index === 0 ? 'is-active' : ''}" style="--depth:${Math.max(0, item.level - 1)}" data-section="${esc(item.id)}">${esc(item.label)}</button>`).join('')}
        <div class="highlight-list"></div>
      </nav>
      <footer class="sidebar-footer">
        <button class="model-trigger" data-command="models"><span class="current-model-label">${esc(data?.currentModel || '选择模型')}</span><span>⌃</span></button>
        <div class="footer-tools"><span>${models.length} 个模型</span><span class="node-count">${nodes.length} 个画布节点</span></div>
      </footer>`;
    renderSidebarHighlights();
  };

  const parseMindmap = (content) => {
    const roots = [];
    const stack = [];
    for (const raw of String(content || '').split(/\r?\n/)) {
      const heading = raw.match(/^(#{1,6})\s+(.+)/);
      const bullet = raw.match(/^(\s*)[-*+]\s+(.+)/);
      if (!heading && !bullet) continue;
      const depth = heading ? heading[1].length - 1 : Math.floor(bullet[1].length / 2) + 1;
      const item = { text: (heading ? heading[2] : bullet[2]).replace(/\*\*/g, ''), children: [] };
      while (stack.length > depth) stack.pop();
      if (!stack.length) roots.push(item);
      else stack[stack.length - 1].children.push(item);
      stack.push(item);
    }
    const draw = (items) => `<ul>${items.map((item) => `<li><button class="mindmap-label">${esc(item.text)}</button>${item.children.length ? draw(item.children) : ''}</li>`).join('')}</ul>`;
    return roots.length ? `<div class="mindmap-tree">${draw(roots)}</div>` : '';
  };

  const currentSectionText = () => {
    const activeId = side.querySelector('[data-section].is-active')?.dataset.section;
    const heading = activeId ? reader.querySelector(`#${CSS.escape(activeId)}`) : null;
    if (!heading) return reader.innerText.slice(0, 16000);
    const level = Number(heading.tagName.slice(1));
    const parts = [heading.innerText];
    let cursor = heading.nextElementSibling;
    while (cursor) {
      const cursorLevel = /^H[1-6]$/.test(cursor.tagName) ? Number(cursor.tagName.slice(1)) : 99;
      if (cursorLevel <= level) break;
      parts.push(cursor.innerText || '');
      cursor = cursor.nextElementSibling;
    }
    return parts.join('\n\n').slice(0, 20000);
  };

  const selectionMarkup = (node) => {
    const text = String(node.selectedText || '');
    if (!text) return '';
    const isFollowupContext = Number(node.parentQuestionId || 0) > 0 && text.length > 240;
    if (isFollowupContext) {
      return `<details class="node-parent-context"><summary>已折叠上一条回答 · ${text.length} 字</summary><div>${esc(text)}</div></details>`;
    }
    return `<button class="node-selection" data-source-start="${node.anchorStart ?? ''}" data-source-end="${node.anchorEnd ?? ''}" title="回到原文">${esc(text)}</button>`;
  };

  const nodeMarkup = (node) => {
    const key = `${node.type}-${node.id}`;
    if (hiddenNodes.has(key)) return '';
    const body = node.type === 'mindmap' ? (parseMindmap(node.content) || node.html) : node.html;
    return `<article class="canvas-node" data-node-id="${node.id}" data-node-type="${node.type}" style="left:${node.x}px;top:${node.y}px;width:${node.width}px;height:${node.height}px">
      <header class="node-title">
        <span>${esc(node.title)}</span><span class="node-badge">${node.type === 'mindmap' ? 'MAP' : 'AI'}</span>
        <button class="node-control" data-node-action="collapse" title="折叠">⌃</button>
        <button class="node-control" data-node-action="edit" title="编辑">✎</button>
        <button class="node-control" data-node-action="delete" title="永久删除">⌫</button>
        <button class="node-control" data-node-action="close" title="关闭窗口">×</button>
      </header>
      <div class="node-body">${selectionMarkup(node)}${body || ''}</div>
      <div class="node-editor"><textarea>${esc(node.content || '')}</textarea><button data-node-action="save">保存修改</button></div>
      ${node.type === 'question' ? '<div class="node-followup"><input placeholder="继续追问这条回答..."/><button data-followup-send title="发送追问">➤</button></div>' : ''}
      <button class="node-resize-handle" data-node-resize title="拖动调整窗口大小" aria-label="调整窗口大小"></button>
    </article>`;
  };

  const pendingMarkup = (item) => `<article class="canvas-node is-pending" data-job-id="${item.localId}" style="left:${item.x}px;top:${item.y}px;width:${item.width || 430}px;height:${item.height || 180}px">
    <header class="node-title"><span>${esc(item.title)}</span><span class="node-badge">AGENT</span><button class="node-control" data-job-cancel title="取消思考">×</button></header>
    <div class="pending-body"><span class="pending-dot"></span><span>正在检索上下文并组织回答，请稍候...</span></div>
    <button class="node-resize-handle" data-node-resize title="拖动调整窗口大小" aria-label="调整窗口大小"></button>
  </article>`;

  const contextHelp = {
    selection: '只发送划选文字', paragraph: '发送当前与相邻段落', section: '发送当前完整章节',
    rag: '检索全文相关片段', document: '发送整份资料'
  };

  const renderCanvas = () => {
    const currentScroll = canvas.querySelector('.canvas-surface')?.scrollTop ?? Number(localStorage.getItem(canvasStateKey) || 0);
    canvas.innerHTML = `
      <div class="canvas-bar">
        <span class="context-help">${contextHelp[contextMode]}</span>
        <button class="canvas-tool icon-tool" data-command="focus-reader" title="专注原文">▣</button>
        <select id="context-select" title="控制发送给模型的资料范围">
          <option value="selection">仅选区</option><option value="paragraph">附近段落</option>
          <option value="section">当前章节</option><option value="rag">文内检索</option><option value="document">整份资料</option>
        </select>
        <button class="canvas-tool" data-tool="note">新建笔记</button>
        <button class="canvas-tool" data-command="prompt-settings">上下文与提示词</button>
        ${data?.canEditDocument ? '<button class="canvas-tool" data-command="edit-document">编辑正文</button>' : ''}
        <button class="canvas-tool" data-tool="mindmap">思维导图</button>
        ${data?.isPaper ? '<button class="canvas-tool" data-tool="paper_summary">5 分钟速读</button>' : ''}
        <button class="canvas-tool closed-node-trigger" data-command="closed-nodes" title="重新打开已关闭的问题">已关闭问题 ${nodes.filter((node) => hiddenNodes.has(`${node.type}-${node.id}`)).length}</button>
      </div>
      <div class="canvas-surface">
        <div class="canvas-scene">${nodes.map(nodeMarkup).join('')}${[...jobs.values()].map(pendingMarkup).join('')}</div>
      </div>
      <div class="canvas-empty" ${nodes.length || jobs.size ? 'hidden' : ''}>划选原文、记录笔记或生成思维导图，结果会留在可编辑画布上</div>
      <section class="prompt-panel" hidden>
        <header><strong>上下文与提示词</strong><button data-command="close-prompt">×</button></header>
        <label>默认上下文<select class="prompt-context"><option value="selection">仅选区</option><option value="paragraph">附近段落</option><option value="section">当前章节</option><option value="rag">文内检索</option><option value="document">整份资料</option></select></label>
        <label>学习偏好<textarea placeholder="例如：先讲直觉，再给严格推导；保留专业术语。">${esc(learningPrompt)}</textarea></label>
        <button class="prompt-save">保存设置</button>
      </section>
      <section class="socratic-panel" hidden>
        <header><strong>苏格拉底学堂</strong><button data-command="close-socratic">×</button></header>
        <p>让 Agent 用连续问题帮助你澄清当前章节，而不是直接给出结论。</p>
        <div class="persona-list">
          <label><input type="radio" name="socratic-persona" value="苏格拉底" checked><span><strong>苏格拉底</strong><small>追问定义与前提</small></span></label>
          <label><input type="radio" name="socratic-persona" value="课程助教"><span><strong>课程助教</strong><small>连接知识点与习题</small></span></label>
          <label><input type="radio" name="socratic-persona" value="反方同学"><span><strong>反方同学</strong><small>寻找漏洞与反例</small></span></label>
        </div>
        <textarea placeholder="这次想弄懂什么？例如：为什么这里需要独立性假设。"></textarea>
        <button class="socratic-start">开始引导</button>
      </section>
      <section class="closed-nodes-menu" hidden>
        <header><strong>已关闭的问题</strong><button data-command="close-closed-nodes">×</button></header>
        <div class="closed-nodes-list"></div>
      </section>`;
    const contextSelect = canvas.querySelector('#context-select');
    contextSelect.value = contextMode;
    canvas.querySelector('.prompt-context').value = contextMode;
    const surface = canvas.querySelector('.canvas-surface');
    surface.scrollTop = currentScroll;
    requestAnimationFrame(() => surface.scrollTop = currentScroll);
    renderMath(canvas);
    canvas.querySelectorAll('.canvas-node[data-node-id]').forEach(observeNode);
    side.querySelector('.node-count')?.replaceChildren(document.createTextNode(`${nodes.length} 个画布节点`));
  };

  const renderClosedNodesMenu = () => {
    const menuElement = canvas.querySelector('.closed-nodes-menu');
    const list = menuElement?.querySelector('.closed-nodes-list');
    if (!menuElement || !list) return;
    const closed = nodes.filter((node) => hiddenNodes.has(`${node.type}-${node.id}`));
    list.innerHTML = closed.length
      ? closed.map((node) => {
          const label = String(node.selectedText || node.title || '未命名问题').replace(/\s+/g, ' ').slice(0, 42);
          return `<button data-reopen-node="${node.type}-${node.id}">${esc(label)}</button>`;
        }).join('')
      : '<p>暂时没有关闭的问题。</p>';
  };

  const observeNode = (node) => {
    nodeResizeObserver.observe(node);
  };

  const applyState = (payload) => {
    if (payload.nodes) nodes = payload.nodes;
    if (payload.highlights) highlights = payload.highlights;
    renderCanvas();
    renderSidebarHighlights();
    syncHighlights();
  };

  const loadState = async () => {
    const payload = await api(`/state?user_id=${userId}&document_id=${documentId}`);
    applyState(payload);
  };

  const persistNodeFrame = (node) => {
    if (!node?.dataset?.nodeId || !node.dataset.nodeType) return;
    api(`/nodes/${node.dataset.nodeType}/${node.dataset.nodeId}`, {
      method: 'PATCH',
      body: requestBody({
        x: Math.round(node.offsetLeft), y: Math.round(node.offsetTop),
        width: Math.round(node.offsetWidth), height: Math.round(node.offsetHeight)
      })
    }).catch((error) => toast(error.message, 'error'));
  };

  const pollJob = async (localId) => {
    const item = jobs.get(localId);
    if (!item?.jobId) return;
    try {
      const payload = await api(`/jobs/${item.jobId}?user_id=${userId}&document_id=${documentId}`);
      const status = payload.job?.status;
      if (status === 'pending') {
        item.timer = setTimeout(() => pollJob(localId), 1200);
        return;
      }
      jobs.delete(localId);
      if (status === 'completed') {
        applyState(payload);
      } else if (status === 'failed') {
        renderCanvas();
        toast(`生成失败：${payload.job?.error || '未知错误'}`, 'error');
      } else {
        renderCanvas();
        toast('已取消本次思考。');
      }
    } catch (error) {
      if (!jobs.has(localId)) return;
      item.retries = (item.retries || 0) + 1;
      if (item.retries < 20) item.timer = setTimeout(() => pollJob(localId), Math.min(5000, 1200 + item.retries * 300));
      else {
        jobs.delete(localId);
        renderCanvas();
        toast(`连接 Reader Agent 失败：${error.message}`, 'error');
      }
    }
  };

  const startJob = async (payload, title) => {
    const localId = `job-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const index = jobs.size;
    jobs.set(localId, { localId, title, x: 28 + index * 32, y: 72 + index * 36, width: 430, height: 180, jobId: null });
    renderCanvas();
    try {
      const response = await api('/jobs', {
        method: 'POST',
        body: requestBody({ ...payload, nonce: Date.now(), context_mode: contextMode, learning_prompt: learningPrompt })
      });
      const item = jobs.get(localId);
      if (!item) {
        await api(`/jobs/${response.job_id}`, { method: 'DELETE', body: requestBody() });
        return;
      }
      item.jobId = response.job_id;
      pollJob(localId);
    } catch (error) {
      jobs.delete(localId);
      renderCanvas();
      toast(error.message, 'error');
    }
  };

  const toggleHighlight = async () => {
    if (!selected || selected.anchorStart == null || selected.anchorEnd == null) {
      toast('数学公式或跨组件选区暂不支持标记，请选择连续原文。', 'error');
      return;
    }
    const previous = highlights.map((item) => ({ ...item }));
    const existing = highlights.find((item) => Number(item.anchor_start) === selected.anchorStart && Number(item.anchor_end) === selected.anchorEnd);
    if (existing) highlights = highlights.filter((item) => item !== existing);
    else highlights.push({
      id: `local-${Date.now()}`, selected_text: selected.text,
      anchor_start: selected.anchorStart, anchor_end: selected.anchorEnd
    });
    syncHighlights();
    renderSidebarHighlights();
    try {
      const payload = await api('/highlights/toggle', {
        method: 'POST',
        body: requestBody({
          selected_text: selected.text, anchor_start: selected.anchorStart, anchor_end: selected.anchorEnd,
          context_prefix: selected.contextPrefix, context_suffix: selected.contextSuffix
        })
      });
      highlights = payload.highlights || [];
      syncHighlights();
      renderSidebarHighlights();
      toast(payload.added ? '已标记为重点。' : '已取消标记。');
    } catch (error) {
      highlights = previous;
      syncHighlights();
      renderSidebarHighlights();
      toast(error.message, 'error');
    }
  };

  const showSelectionMenu = () => {
    const payload = selectionPayload();
    if (!payload) {
      menu.style.display = 'none';
      return;
    }
    selected = payload;
    menu.style.left = `${Math.max(8, Math.min(payload.rect.left, window.innerWidth - 345))}px`;
    menu.style.top = `${Math.max(8, Math.min(payload.rect.bottom + 7, window.innerHeight - 390))}px`;
    menu.style.display = 'block';
    menu.querySelector('.custom-ask').style.display = 'none';
    menu.querySelectorAll('.selection-action').forEach((item) => item.style.display = 'grid');
    const markLabel = menu.querySelector('[data-action="highlight"] strong');
    if (markLabel) markLabel.textContent = highlightIsSelected() ? '取消标记' : '标记重点';
  };

  const openComposer = (mode) => {
    menu.querySelectorAll('.selection-action').forEach((item) => item.style.display = 'none');
    const composer = menu.querySelector('.custom-ask');
    composer.dataset.mode = mode;
    composer.style.display = 'block';
    composer.querySelector('textarea').placeholder = mode === 'note' ? '写下你的笔记...' : '关于这段内容，你还想问什么？';
    composer.querySelector('button').textContent = mode === 'note' ? '保存笔记' : '发送提问';
    composer.querySelector('textarea').focus();
  };

  renderSidebar();
  reader.innerHTML = data?.html || '<p>暂无可阅读内容。</p>';
  renderMath(reader);
  syncHighlights();
  const savedWidth = Number(localStorage.getItem(widthKey));
  if (savedWidth >= 420) root.style.setProperty('--reader-width', `${savedWidth}px`);
  const savedSidebarWidth = Number(localStorage.getItem(sidebarWidthKey));
  if (savedSidebarWidth >= 210) root.style.setProperty('--sidebar-width', `${savedSidebarWidth}px`);
  reader.scrollTop = Number(localStorage.getItem(readerStateKey) || data?.readerScroll || 0);

  menu.innerHTML = `
    <button class="selection-action" data-action="note"><strong>笔记</strong><small>记录自己的理解与疑问</small></button>
    <button class="selection-action" data-action="explain"><strong>解释</strong><small>拆解选中内容的直觉与步骤</small></button>
    <button class="selection-action" data-action="variable"><strong>变量含义</strong><small>说明符号类型、范围和作用</small></button>
    <button class="selection-action" data-action="why"><strong>为什么</strong><small>核对这一步成立的条件</small></button>
    <button class="selection-action" data-action="example"><strong>举例</strong><small>给一个具体、可验证的例子</small></button>
    <button class="selection-action" data-action="solve"><strong>解题</strong><small>按步骤完成选中的题目</small></button>
    <button class="selection-action" data-action="mindmap"><strong>思维导图</strong><small>把选中内容整理成可折叠结构</small></button>
    <button class="selection-action" data-action="highlight"><strong>标记重点</strong><small>保存准确位置，下次打开仍保留</small></button>
    <button class="selection-action" data-action="custom"><strong>自定义提问</strong><small>带着当前选区自由追问</small></button>
    <div class="custom-ask"><textarea></textarea><button class="custom-send">发送提问</button></div>`;
  modelMenu.innerHTML = `<div class="model-head">模型选择</div>${(data?.models || []).map((model) => `
    <button class="model-option ${model.current ? 'is-current' : ''}" data-model="${model.id}"><span>${esc(model.label)}</span><small>${model.current ? '当前' : '切换'}</small></button>`).join('') || '<div class="model-head">尚未添加模型</div>'}
    <button class="model-option" data-command="subscription"><span>管理模型与订阅</span><small>打开</small></button>`;

  const resizeTimers = new Map();
  const nodeResizeObserver = new ResizeObserver((entries) => entries.forEach((entry) => {
    const node = entry.target;
    if (!node.dataset.nodeId) return;
    clearTimeout(resizeTimers.get(node));
    resizeTimers.set(node, setTimeout(() => persistNodeFrame(node), 450));
  }));
  renderCanvas();

  const onClick = async (event) => {
    if (event.target.closest('.prompt-save')) {
      onPromptSave();
      return;
    }
    if (event.target.closest('.socratic-start')) {
      const panel = canvas.querySelector('.socratic-panel');
      const persona = panel.querySelector('input[name="socratic-persona"]:checked')?.value || '苏格拉底';
      const goal = panel.querySelector('textarea').value.trim() || '帮助我检查是否真正理解当前章节。';
      panel.hidden = true;
      await startJob({
        kind: 'selection',
        action: 'socratic',
        selected_text: currentSectionText(),
        custom_question: `你现在扮演${persona}。学习目标：${goal}`
      }, `${persona}正在提问`);
      return;
    }
    const commandButton = event.target.closest('[data-command]');
    const command = commandButton?.dataset.command;
    if (command === 'back' || command === 'subscription' || command === 'edit-document') {
      setTriggerValue('command', { name: command, nonce: Date.now() });
      return;
    }
    if (command === 'collapse-side') {
      root.classList.toggle('side-collapsed');
      commandButton.title = root.classList.contains('side-collapsed') ? '展开目录' : '收起目录';
      return;
    }
    if (command === 'focus-reader') {
      root.classList.toggle('reader-focused');
      return;
    }
    if (command === 'models') {
      const rect = commandButton.getBoundingClientRect();
      modelMenu.style.left = `${rect.left}px`;
      modelMenu.style.bottom = `${window.innerHeight - rect.top + 4}px`;
      modelMenu.style.display = modelMenu.style.display === 'block' ? 'none' : 'block';
      return;
    }
    if (command === 'closed-nodes') {
      const panel = canvas.querySelector('.closed-nodes-menu');
      renderClosedNodesMenu();
      panel.hidden = !panel.hidden;
      return;
    }
    if (command === 'close-closed-nodes') {
      canvas.querySelector('.closed-nodes-menu').hidden = true;
      return;
    }
    if (command === 'prompt-settings') {
      canvas.querySelector('.prompt-panel').hidden = false;
      return;
    }
    if (command === 'close-prompt') {
      canvas.querySelector('.prompt-panel').hidden = true;
      return;
    }
    if (command === 'close-socratic') {
      canvas.querySelector('.socratic-panel').hidden = true;
      return;
    }

    const reopenKey = event.target.closest('[data-reopen-node]')?.dataset.reopenNode;
    if (reopenKey) {
      hiddenNodes.delete(reopenKey);
      renderCanvas();
      canvas.querySelector('.closed-nodes-menu').hidden = false;
      renderClosedNodesMenu();
      return;
    }

    const section = event.target.closest('[data-section]');
    if (section) {
      reader.querySelector(`#${CSS.escape(section.dataset.section)}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    const sourceAnchor = event.target.closest('[data-source-start]');
    if (sourceAnchor) {
      const start = Number(sourceAnchor.dataset.sourceStart);
      const end = Number(sourceAnchor.dataset.sourceEnd);
      const range = Number.isFinite(start) && Number.isFinite(end) && end > start ? rangeFromOffsets(start, end) : null;
      if (range) {
        const rect = range.getBoundingClientRect();
        const readerRect = reader.getBoundingClientRect();
        reader.scrollTop += rect.top - readerRect.top - reader.clientHeight * 0.3;
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        setTimeout(() => selection.removeAllRanges(), 1600);
      }
      return;
    }
    const highlightRow = event.target.closest('[data-highlight-anchor]');
    if (highlightRow && !event.target.closest('[data-highlight-delete]')) {
      const item = highlights.find((value) => String(value.id) === String(highlightRow.dataset.highlightAnchor));
      const range = item ? rangeFromOffsets(Number(item.anchor_start), Number(item.anchor_end)) : null;
      if (range) {
        const rect = range.getBoundingClientRect();
        const readerRect = reader.getBoundingClientRect();
        reader.scrollTop += rect.top - readerRect.top - reader.clientHeight * 0.35;
      }
      return;
    }
    const deleteHighlightId = event.target.closest('[data-highlight-delete]')?.dataset.highlightDelete;
    if (deleteHighlightId) {
      const previous = highlights;
      highlights = highlights.filter((item) => String(item.id) !== String(deleteHighlightId));
      syncHighlights();
      renderSidebarHighlights();
      try {
        await api(`/highlights/${deleteHighlightId}`, { method: 'DELETE', body: requestBody() });
      } catch (error) {
        highlights = previous;
        syncHighlights();
        renderSidebarHighlights();
        toast(error.message, 'error');
      }
      return;
    }

    const modelButton = event.target.closest('[data-model]');
    if (modelButton) {
      try {
        await api('/models/activate', { method: 'POST', body: requestBody({ model_id: Number(modelButton.dataset.model) }) });
        modelMenu.querySelectorAll('.model-option[data-model]').forEach((button) => {
          const current = button === modelButton;
          button.classList.toggle('is-current', current);
          button.querySelector('small').textContent = current ? '当前' : '切换';
        });
        side.querySelector('.current-model-label').textContent = modelButton.querySelector('span').textContent;
        modelMenu.style.display = 'none';
        toast('阅读模型已切换。');
      } catch (error) {
        toast(error.message, 'error');
      }
      return;
    }

    const action = event.target.closest('[data-action]')?.dataset.action;
    if (action) {
      if (action === 'highlight') await toggleHighlight();
      else if (action === 'custom' || action === 'note') openComposer(action);
      else if (action === 'mindmap' && selected) {
        await startJob({ kind: 'mindmap', source_text: selected.text }, '正在生成选区思维导图');
        menu.style.display = 'none';
      }
      else if (selected) {
        await startJob({
          kind: 'selection', action, selected_text: selected.text,
          anchor_start: selected.anchorStart, anchor_end: selected.anchorEnd,
          parent_question_id: selected.sourceNodeId
        }, action === 'solve' ? '正在解题' : '正在阅读选区');
        menu.style.display = 'none';
      }
      return;
    }

    const tool = event.target.closest('[data-tool]')?.dataset.tool;
    if (tool === 'mindmap' || tool === 'paper_summary') {
      await startJob(
        { kind: tool, source_text: tool === 'mindmap' ? currentSectionText() : '' },
        tool === 'mindmap' ? '正在生成当前章节思维导图' : '正在速读论文'
      );
      return;
    }
    if (tool === 'socratic') {
      canvas.querySelector('.socratic-panel').hidden = false;
      return;
    }
    if (tool === 'note') {
      try {
        const payload = await api('/notes', { method: 'POST', body: requestBody({ content: '### 阅读笔记\n\n在这里记录你的想法。' }) });
        applyState(payload);
      } catch (error) { toast(error.message, 'error'); }
      return;
    }

    const jobCancel = event.target.closest('[data-job-cancel]');
    if (jobCancel) {
      const node = jobCancel.closest('[data-job-id]');
      const item = jobs.get(node?.dataset.jobId);
      if (item) {
        jobs.delete(item.localId);
        clearTimeout(item.timer);
        renderCanvas();
        if (item.jobId) api(`/jobs/${item.jobId}`, { method: 'DELETE', body: requestBody() }).catch(() => {});
      }
      return;
    }

    const control = event.target.closest('[data-node-action]');
    if (control) {
      const node = control.closest('.canvas-node');
      const type = node?.dataset.nodeType;
      const id = Number(node?.dataset.nodeId || 0);
      const kind = control.dataset.nodeAction;
      if (!type || !id) return;
      if (kind === 'close') {
        hiddenNodes.add(`${type}-${id}`);
        renderCanvas();
      } else if (kind === 'collapse') {
        node.classList.toggle('is-collapsed');
        control.textContent = node.classList.contains('is-collapsed') ? '⌄' : '⌃';
      } else if (kind === 'delete') {
        node.remove();
        nodes = nodes.filter((item) => !(item.type === type && Number(item.id) === id));
        await api(`/nodes/${type}/${id}`, { method: 'DELETE', body: requestBody() }).catch((error) => toast(error.message, 'error'));
      } else if (kind === 'edit') {
        node.querySelector('.node-body').style.display = 'none';
        node.querySelector('.node-editor').style.display = 'block';
      } else if (kind === 'save') {
        const content = node.querySelector('textarea').value;
        await api(`/nodes/${type}/${id}`, { method: 'PATCH', body: requestBody({ content }) });
        await loadState();
      }
      side.querySelector('.node-count').textContent = `${nodes.length} 个画布节点`;
      return;
    }

    const followup = event.target.closest('[data-followup-send]');
    if (followup) {
      const nodeElement = followup.closest('.canvas-node');
      const input = nodeElement.querySelector('.node-followup input');
      const question = input.value.trim();
      const sourceNode = nodes.find((item) => item.type === nodeElement.dataset.nodeType && Number(item.id) === Number(nodeElement.dataset.nodeId));
      if (question && sourceNode) {
        input.value = '';
        await startJob({
          kind: 'selection',
          action: 'question',
          selected_text: String(sourceNode.content || '').slice(0, 12000),
          custom_question: question,
          parent_question_id: Number(sourceNode.id)
        }, '正在继续追问');
      }
      return;
    }

    const mindmapLabel = event.target.closest('.mindmap-label');
    if (mindmapLabel) {
      const child = mindmapLabel.parentElement.querySelector(':scope > ul');
      if (child) child.hidden = !child.hidden;
    }
  };

  const onCustomSend = async () => {
    const composer = menu.querySelector('.custom-ask');
    const text = composer.querySelector('textarea').value.trim();
    if (!text || !selected) return;
    if (composer.dataset.mode === 'note') {
      try {
        const content = `### 阅读笔记\n\n> ${selected.text}\n\n${text}`;
        const payload = await api('/notes', { method: 'POST', body: requestBody({ content }) });
        applyState(payload);
        menu.style.display = 'none';
      } catch (error) { toast(error.message, 'error'); }
    } else {
      await startJob({
        kind: 'selection', action: 'question', selected_text: selected.text, custom_question: text,
        anchor_start: selected.anchorStart, anchor_end: selected.anchorEnd,
        parent_question_id: selected.sourceNodeId
      }, '正在回答自定义问题');
      menu.style.display = 'none';
    }
    composer.querySelector('textarea').value = '';
  };

  const resizeEdgeForPointer = (node, event) => {
    const rect = node.getBoundingClientRect();
    const zone = 8;
    const horizontal = event.clientX - rect.left <= zone ? 'w' : rect.right - event.clientX <= zone ? 'e' : '';
    const vertical = event.clientY - rect.top <= zone ? 'n' : rect.bottom - event.clientY <= zone ? 's' : '';
    return `${vertical}${horizontal}`;
  };

  const beginNodeResize = (node, edge, event) => {
    nodeResizeState = {
      node,
      job: jobs.get(node.dataset.jobId),
      edge,
      startX: event.clientX,
      startY: event.clientY,
      left: node.offsetLeft,
      top: node.offsetTop,
      width: node.offsetWidth,
      height: node.offsetHeight
    };
    event.preventDefault();
  };

  const resizeNodeFromPointer = (state, event) => {
    const minWidth = 300;
    const minHeight = 180;
    const maxWidth = 1200;
    const maxHeight = 1000;
    const dx = event.clientX - state.startX;
    const dy = event.clientY - state.startY;
    let left = state.left;
    let top = state.top;
    let width = state.width;
    let height = state.height;
    if (state.edge.includes('e')) width = Math.max(minWidth, Math.min(maxWidth, state.width + dx));
    if (state.edge.includes('s')) height = Math.max(minHeight, Math.min(maxHeight, state.height + dy));
    if (state.edge.includes('w')) {
      width = Math.max(minWidth, Math.min(maxWidth, state.width - dx));
      left = state.left + state.width - width;
    }
    if (state.edge.includes('n')) {
      height = Math.max(minHeight, Math.min(maxHeight, state.height - dy));
      top = state.top + state.height - height;
    }
    state.node.style.left = `${Math.max(0, left)}px`;
    state.node.style.top = `${Math.max(0, top)}px`;
    state.node.style.width = `${width}px`;
    state.node.style.height = `${height}px`;
    if (state.job) {
      state.job.x = state.node.offsetLeft;
      state.job.y = state.node.offsetTop;
      state.job.width = state.node.offsetWidth;
      state.job.height = state.node.offsetHeight;
    }
  };

  const onPointerDown = (event) => {
    const closedPanel = canvas.querySelector('.closed-nodes-menu');
    if (!closedPanel?.hidden && !event.target.closest('.closed-nodes-menu,.closed-node-trigger')) {
      closedPanel.hidden = true;
    }
    if (event.target === sidebarResizer) {
      resizingSidebar = true;
      sidebarResizer.classList.add('is-dragging');
      event.preventDefault();
      return;
    }
    if (event.target === resizer) {
      resizingReader = true;
      resizer.classList.add('is-dragging');
      event.preventDefault();
      return;
    }
    const node = event.target.closest('.canvas-node');
    const edge = node ? resizeEdgeForPointer(node, event) : '';
    if (node && edge) {
      beginNodeResize(node, edge, event);
      event.preventDefault();
      return;
    }
    const resizeHandle = event.target.closest('[data-node-resize]');
    if (resizeHandle) {
      const resizeNode = resizeHandle.closest('.canvas-node');
      if (resizeNode) beginNodeResize(resizeNode, 'se', event);
      return;
    }
    const header = event.target.closest('.node-title');
    if (header && !event.target.closest('.node-control')) {
      const dragNode = header.closest('.canvas-node');
      if (dragNode?.dataset.nodeId || dragNode?.dataset.jobId) {
        dragState = {
          node: dragNode, job: jobs.get(dragNode.dataset.jobId), startX: event.clientX, startY: event.clientY,
          left: dragNode.offsetLeft, top: dragNode.offsetTop
        };
        event.preventDefault();
      }
      return;
    }
    const surface = event.target.closest('.canvas-surface');
    if (surface && !event.target.closest('.canvas-node')) {
      canvas.querySelector('.closed-nodes-menu')?.setAttribute('hidden', '');
      canvasPan = { surface, startX: event.clientX, startY: event.clientY, left: surface.scrollLeft, top: surface.scrollTop };
    }
  };

  const onPointerMove = (event) => {
    if (resizingSidebar) {
      const rootLeft = root.getBoundingClientRect().left;
      root.style.setProperty('--sidebar-width', `${Math.max(210, Math.min(460, event.clientX - rootLeft))}px`);
      return;
    }
    if (resizingReader) {
      const rootLeft = root.getBoundingClientRect().left;
      const leftWidth = side.offsetWidth + sidebarResizer.offsetWidth;
      const max = Math.max(420, root.clientWidth - leftWidth - 330);
      root.style.setProperty('--reader-width', `${Math.max(420, Math.min(max, event.clientX - rootLeft - leftWidth))}px`);
      return;
    }
    if (dragState) {
      dragState.node.style.left = `${Math.max(0, dragState.left + event.clientX - dragState.startX)}px`;
      dragState.node.style.top = `${Math.max(0, dragState.top + event.clientY - dragState.startY)}px`;
      if (dragState.job) {
        dragState.job.x = dragState.node.offsetLeft;
        dragState.job.y = dragState.node.offsetTop;
      }
      return;
    }
    if (nodeResizeState) {
      resizeNodeFromPointer(nodeResizeState, event);
      return;
    }
    if (canvasPan) {
      canvasPan.surface.scrollLeft = canvasPan.left - (event.clientX - canvasPan.startX);
      canvasPan.surface.scrollTop = canvasPan.top - (event.clientY - canvasPan.startY);
    }
  };

  const onPointerUp = () => {
    if (resizingSidebar) {
      resizingSidebar = false;
      sidebarResizer.classList.remove('is-dragging');
      localStorage.setItem(sidebarWidthKey, String(Math.round(side.offsetWidth)));
    }
    if (resizingReader) {
      resizingReader = false;
      resizer.classList.remove('is-dragging');
      localStorage.setItem(widthKey, String(Math.round(reader.offsetWidth)));
    }
    if (dragState?.node?.dataset.nodeId) persistNodeFrame(dragState.node);
    dragState = null;
    if (nodeResizeState?.node?.dataset.nodeId) persistNodeFrame(nodeResizeState.node);
    nodeResizeState = null;
    canvasPan = null;
  };

  const onChange = (event) => {
    if (event.target.matches('#context-select,.prompt-context')) {
      contextMode = event.target.value;
      localStorage.setItem(contextKey, contextMode);
      canvas.querySelector('#context-select').value = contextMode;
      canvas.querySelector('.prompt-context').value = contextMode;
      canvas.querySelector('.context-help').textContent = contextHelp[contextMode];
    }
  };

  const onPromptSave = () => {
    learningPrompt = canvas.querySelector('.prompt-panel textarea').value.trim();
    localStorage.setItem(learningKey, learningPrompt);
    canvas.querySelector('.prompt-panel').hidden = true;
    toast('上下文与学习提示词已保存。');
  };

  const onKeyDown = (event) => {
    if (event.key === 'Enter' && event.target.matches('.node-followup input') && !event.shiftKey) {
      event.preventDefault();
      event.target.parentElement.querySelector('[data-followup-send]')?.click();
    }
    if (event.key === 'Escape') {
      menu.style.display = 'none';
      modelMenu.style.display = 'none';
      canvas.querySelector('.prompt-panel').hidden = true;
      canvas.querySelector('.socratic-panel').hidden = true;
    }
  };

  const preventSelectionLoss = (event) => event.preventDefault();
  const customSend = menu.querySelector('.custom-send');
  const onCanvasSelection = (event) => {
    if (event.target.closest('.node-body')) showSelectionMenu();
  };
  reader.addEventListener('mouseup', showSelectionMenu);
  canvas.addEventListener('mouseup', onCanvasSelection);
  reader.addEventListener('scroll', () => localStorage.setItem(readerStateKey, String(reader.scrollTop)), { passive: true });
  root.addEventListener('click', onClick);
  root.addEventListener('change', onChange);
  root.addEventListener('pointerdown', onPointerDown);
  root.addEventListener('pointermove', onPointerMove);
  root.addEventListener('pointerup', onPointerUp);
  root.addEventListener('pointercancel', onPointerUp);
  root.addEventListener('keydown', onKeyDown);
  menu.addEventListener('mousedown', preventSelectionLoss);
  customSend.addEventListener('click', onCustomSend);

  const headings = [...reader.querySelectorAll('h1[id],h2[id],h3[id]')];
  const chapterObserver = new IntersectionObserver((entries) => {
    const active = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (!active) return;
    side.querySelectorAll('[data-section]').forEach((button) => button.classList.toggle('is-active', button.dataset.section === active.target.id));
  }, { root: reader, rootMargin: '-10% 0px -75% 0px' });
  headings.forEach((heading) => chapterObserver.observe(heading));

  return () => {
    jobs.forEach((item) => clearTimeout(item.timer));
    nodeResizeObserver.disconnect();
    chapterObserver.disconnect();
    CSS.highlights?.delete('nju-reader-marks');
    reader.removeEventListener('mouseup', showSelectionMenu);
    canvas.removeEventListener('mouseup', onCanvasSelection);
    root.removeEventListener('click', onClick);
    root.removeEventListener('change', onChange);
    root.removeEventListener('pointerdown', onPointerDown);
    root.removeEventListener('pointermove', onPointerMove);
    root.removeEventListener('pointerup', onPointerUp);
    root.removeEventListener('pointercancel', onPointerUp);
    root.removeEventListener('keydown', onKeyDown);
    menu.removeEventListener('mousedown', preventSelectionLoss);
    customSend.removeEventListener('click', onCustomSend);
  };
}
