import html as html_lib
import re

import markdown
import streamlit as st
from latex2mathml.converter import convert as latex_to_mathml


HALL_HTML = '<main id="library-hall"><div class="hall-loading">正在整理资料库...</div></main>'
HALL_CSS = """
:host { display:block; }
* { box-sizing:border-box; }
#library-hall { min-height:720px; padding:54px clamp(28px,10vw,170px) 90px; color:#20232a;
  background-color:#fcfcfd; background-image:linear-gradient(#f0eaf6 1px,transparent 1px),linear-gradient(90deg,#f0eaf6 1px,transparent 1px);
  background-size:96px 96px; font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
.hall-kicker { color:#147d75; font-size:12px; font-weight:750; letter-spacing:.14em; }
.hall-title { margin:12px 0 58px; text-align:center; font-family:Georgia,"Songti SC",serif; font-size:42px; font-weight:600; color:#20232a; }
.hall-grid { display:grid; grid-template-columns:repeat(4,minmax(160px,1fr)); border-top:1px solid #ddd5e5; border-left:1px solid #ddd5e5; box-shadow:0 14px 34px rgba(50,33,63,.05); }
.hall-item { min-height:138px; padding:28px 24px; border:0; border-right:1px solid #ddd5e5; border-bottom:1px solid #ddd5e5;
  background:rgba(255,255,255,.94); color:#20232a; text-align:left; cursor:pointer; transition:background .16s ease,transform .16s ease; }
.hall-item:hover { position:relative; z-index:1; background:#f5f0f8; transform:translateY(-2px); }
.hall-item strong { display:block; margin-bottom:14px; font-size:17px; }
.hall-item small { color:#686c75; }
.hall-item.is-featured { background:#f0eaf6; }
.hall-item.is-featured strong { color:#5b2a86; }
.hall-item.is-disabled { cursor:default; opacity:.48; }
.hall-foot { margin-top:24px; color:#686c75; font-size:13px; }
@media(max-width:900px){.hall-grid{grid-template-columns:1fr 1fr}.hall-title{text-align:left;margin-bottom:36px}}
"""
HALL_JS = """
export default function(component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement.querySelector('#library-hall');
  const categories = data?.categories || [];
  root.innerHTML = `
    <div class="hall-kicker">NJU-SZ KNOWLEDGE COMMONS</div>
    <h1 class="hall-title">资料库分类</h1>
    <div class="hall-grid">${categories.map(item => `
      <button class="hall-item ${item.featured?'is-featured':''} ${item.disabled?'is-disabled':''}" data-key="${item.key}" ${item.disabled?'disabled':''}>
        <strong>${item.label}</strong><small>${item.count} 份资料${item.note?` · ${item.note}`:''}</small>
      </button>`).join('')}</div>
    <div class="hall-foot">个人资料仅当前账号可见；公共资料库将在后续版本接入。</div>`;
  const onClick = (event) => {
    const button = event.target.closest('[data-key]');
    if (!button || button.disabled) return;
    setTriggerValue('open', { key:button.dataset.key, nonce:Date.now() });
  };
  root.addEventListener('click', onClick);
  return () => root.removeEventListener('click', onClick);
}
"""


COLLECTION_HTML = '<main id="collection-view"><div class="collection-loading">正在打开资料库...</div></main>'
COLLECTION_CSS = """
:host{display:block}*{box-sizing:border-box}
#collection-view{min-height:720px;padding:48px clamp(22px,7vw,120px) 90px;background:#fcfcfd;color:#20232a;
font-family:"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.collection-shell{display:grid;grid-template-columns:260px minmax(0,1fr);gap:18px;max-width:1320px;margin:0 auto}
.collection-side,.collection-main{border:1px solid #e1e2e6;background:#fff;box-shadow:0 12px 30px rgba(50,33,63,.04)}
.collection-side{padding:18px}.back-button,.category-button{width:100%;border:0;background:transparent;color:#484b53;text-align:left;cursor:pointer}
.back-button{height:42px;margin-bottom:16px;border:1px solid #d6d7dc;padding:0 14px}.side-title{margin:18px 10px 14px;font-size:19px;color:#20232a}
.category-button{display:flex;justify-content:space-between;padding:11px 12px;border-radius:4px}.category-button:hover,.category-button.is-active{background:#f0eaf6;color:#5b2a86}
.category-button small{color:#858993}.collection-main{min-height:520px;padding:20px}
.collection-head{display:flex;justify-content:space-between;align-items:center;gap:20px;padding:4px 0 20px;border-bottom:1px solid #e1e2e6}
.collection-title{margin:0;font-size:22px;color:#20232a}.build-button{height:40px;padding:0 18px;border:1px solid #5b2a86;background:#5b2a86;color:white;font-weight:700;cursor:pointer;border-radius:5px}
.doc-list{display:grid;gap:12px;padding-top:16px}.doc-row{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:20px;padding:18px;border:1px solid #e1e2e6;background:#fcfcfd}
.doc-row:hover{border-color:#bca8cf;background:#faf7fc}.doc-title{font-size:16px;font-weight:700}.doc-meta{margin-top:7px;color:#777b84;font-size:13px}.doc-actions{display:flex;gap:8px}
.doc-actions button{height:38px;padding:0 18px;border:1px solid #bca8cf;background:white;color:#5b2a86;font-weight:650;cursor:pointer;border-radius:5px}.doc-actions .study{background:#5b2a86;color:white;border-color:#5b2a86}
.empty-library{padding:90px 20px;text-align:center;color:#777b84}.empty-library strong{display:block;margin-bottom:12px;color:#20232a;font-size:20px}
@media(max-width:800px){.collection-shell{grid-template-columns:1fr}.collection-side{display:none}.doc-row{grid-template-columns:1fr}.collection-head{align-items:flex-start}}
"""
COLLECTION_JS = """
export default function(component){
 const{data,parentElement,setTriggerValue}=component;const root=parentElement.querySelector('#collection-view');
 const cats=data?.categories||[],docs=data?.documents||[],active=data?.active||'custom';
 root.innerHTML=`<div class="collection-shell"><aside class="collection-side"><button class="back-button" data-command="back">← 返回分类大厅</button><h2 class="side-title">资料库分类</h2>${cats.map(c=>`<button class="category-button ${c.key===active?'is-active':''}" data-category="${c.key}"><span>${c.label}</span><small>${c.count}</small></button>`).join('')}</aside>
 <section class="collection-main"><header class="collection-head"><div><h1 class="collection-title">${data?.title||'自定义资料库'}</h1><div class="doc-meta">${docs.length} 份资料 · 由当前账号维护</div></div><button class="build-button" data-command="add">＋ 构建新资料</button></header>
 ${docs.length?`<div class="doc-list">${docs.map(d=>`<article class="doc-row"><div><div class="doc-title">${d.title}</div><div class="doc-meta">${d.kind} · ${d.status}${d.pages?` · ${d.pages} 页`:''}</div></div><div class="doc-actions"><button data-reprocess="${d.id}" title="使用当前模型重新识别章节和排版">重新整理</button><button data-open="${d.id}" class="study">学习</button></div></article>`).join('')}</div>`:`<div class="empty-library"><strong>这里还没有资料</strong><span>点击“构建新资料”，把 PDF、PPTX 或 Markdown 整理成可交互原文。</span></div>`}</section></div>`;
 const click=e=>{const t=e.target.closest('button');if(!t)return;if(t.dataset.command)setTriggerValue('command',{name:t.dataset.command,nonce:Date.now()});if(t.dataset.category)setTriggerValue('category',{key:t.dataset.category,nonce:Date.now()});if(t.dataset.open)setTriggerValue('open_document',{id:Number(t.dataset.open),nonce:Date.now()});if(t.dataset.reprocess)setTriggerValue('reprocess_document',{id:Number(t.dataset.reprocess),nonce:Date.now()})};
 root.addEventListener('click',click);return()=>root.removeEventListener('click',click);
}
"""


WORKSPACE_HTML = """
<main id="study-workspace">
  <aside id="study-sidebar"></aside>
  <section id="study-reader"></section>
  <div id="reader-resizer" title="拖动调整原文宽度"></div>
  <section id="study-canvas"></section>
  <div id="selection-menu"></div>
  <div id="model-menu"></div>
</main>
"""
WORKSPACE_CSS = """
:host{display:block}*{box-sizing:border-box}
#study-workspace{--reader-width:620px;position:relative;display:grid;grid-template-columns:280px minmax(420px,var(--reader-width)) 6px minmax(320px,1fr);height:100vh;overflow:hidden;background:#f7f5f9;color:#20232a;font-family:Georgia,"Songti SC","Microsoft YaHei",serif}
#study-sidebar{position:relative;display:flex;flex-direction:column;border-right:1px solid #ddd5e5;background:#f0eaf6;overflow:hidden}
.side-top{display:flex;align-items:center;gap:8px;height:38px;padding:0 14px;border-bottom:1px solid #ddd5e5;font-size:13px;color:#44235f}.workspace-badge{padding:3px 8px;border-radius:10px;background:#5b2a86;color:white;font-family:"Segoe UI",sans-serif;font-size:11px}
.back-workspace{margin-left:auto;border:0;background:transparent;color:#5b2a86;cursor:pointer;font-size:18px}.side-doc{padding:14px 18px 8px;color:#5b2a86;font-weight:700}
.section-list{flex:1;overflow:auto;padding:0 0 190px}.section-label{padding:12px 18px 5px;color:#86798e;font-family:"Segoe UI",sans-serif;font-size:11px;font-weight:750;letter-spacing:.08em}.section-button{display:block;width:100%;padding:7px 20px 7px calc(20px + var(--depth,0)*14px);border:0;background:transparent;color:#4c4652;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
.section-button:hover,.section-button.is-active{background:#5b2a86;color:white}.sidebar-footer{position:absolute;left:0;right:0;bottom:0;padding:10px 12px;border-top:1px solid #ddd5e5;background:#f0eaf6}
.model-trigger{display:flex;justify-content:space-between;width:100%;height:38px;padding:0 10px;border:1px solid #cbb8dc;background:white;color:#44235f;align-items:center;cursor:pointer}.footer-tools{display:flex;justify-content:space-between;margin-top:8px;color:#77717e;font-family:"Segoe UI",sans-serif;font-size:12px}
#study-reader{height:100vh;overflow:auto;padding:30px clamp(30px,4vw,56px) 100px;background:#fff;line-height:1.82;font-size:16px}
#study-reader h1{margin:0 0 24px;font-size:30px}#study-reader h2{margin:28px 0 12px;font-size:22px}#study-reader h3{margin:22px 0 10px;font-size:18px}#study-reader p{margin:0 0 1.05em}
#study-reader blockquote{margin:16px 0;padding:14px 16px;border-left:3px solid #147d75;background:#eef8f6;color:#3b4c49}#study-reader pre{overflow:auto;padding:12px;background:#f5f2f7}#study-reader code{font-family:Consolas,monospace}
#study-reader table{width:100%;border-collapse:collapse}#study-reader th,#study-reader td{padding:8px;border:1px solid #d7d8dc}#study-reader img{max-width:100%;border-radius:6px}#study-reader ::selection{background:#5b2a86;color:white}#study-reader mark{padding:1px 2px;background:#ffe58a;color:inherit;border-bottom:2px solid #e7b93f}
#study-reader math,.node-body math{max-width:100%;overflow-x:auto}.math-block{display:block;margin:14px 0;text-align:center;overflow-x:auto}
#reader-resizer{height:100vh;background:#ddd5e5;cursor:col-resize;transition:background .15s}#reader-resizer:hover,#reader-resizer.is-dragging{background:#5b2a86}
#study-canvas{position:relative;height:100vh;overflow:hidden;background-color:#f7f5f9;background-image:linear-gradient(#e5ddeb 1px,transparent 1px),linear-gradient(90deg,#e5ddeb 1px,transparent 1px);background-size:24px 24px}
.canvas-bar{position:absolute;z-index:30;left:0;right:0;top:0;display:flex;justify-content:flex-end;align-items:center;gap:7px;height:38px;padding:0 12px;border-bottom:1px solid #ddd5e5;background:#f0eaf6}.canvas-bar select,.canvas-tool{height:28px;border:1px solid #cbb8dc;background:white;color:#4d3e56;padding:0 9px}.canvas-tool{cursor:pointer}.context-help{margin-right:auto;color:#776d7d;font-family:"Segoe UI",sans-serif;font-size:11px}
.canvas-surface{position:absolute;inset:38px 0 0;overflow:auto}.canvas-node{position:absolute;min-width:300px;min-height:180px;max-width:calc(100% - 12px);resize:both;overflow:hidden;border:1px solid #cbb8dc;background:white;box-shadow:0 14px 34px rgba(50,33,63,.14)}
.node-title{display:flex;align-items:center;gap:8px;height:40px;padding:0 8px 0 12px;border-bottom:1px solid #e1e2e6;color:#5b2a86;font-family:"Segoe UI",sans-serif;font-weight:700;cursor:move;user-select:none}.node-title span:first-child{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.node-badge{flex:none;color:#147d75;font-size:11px}.node-control{display:grid;place-items:center;width:28px;height:28px;border:0;background:transparent;color:#686c75;cursor:pointer;font-size:15px}.node-control:hover{background:#f0eaf6;color:#5b2a86}.node-body{height:calc(100% - 40px);padding:16px 18px;overflow:auto;line-height:1.7}.node-body h1,.node-body h2{font-size:18px}.node-selection{margin:-2px 0 12px;padding:8px 10px;border-left:3px solid #e7b93f;background:#fff9e8;color:#686c75;font-size:12px}.node-editor{display:none;height:calc(100% - 40px);padding:12px}.node-editor textarea{width:100%;height:calc(100% - 42px);padding:10px;border:1px solid #cbb8dc;background:#fcfcfd;color:#20232a;resize:none}.node-editor button{width:100%;height:34px;margin-top:6px;border:0;background:#5b2a86;color:white;cursor:pointer}.canvas-empty{position:absolute;inset:38px 0 0;display:grid;place-items:center;color:#9b96a1;font-family:"Segoe UI",sans-serif;pointer-events:none}
#selection-menu{position:fixed;z-index:40;display:none;width:320px;padding:6px;border:1px solid #cbb8dc;background:white;box-shadow:0 16px 40px rgba(50,33,63,.18);font-family:"Segoe UI","Microsoft YaHei",sans-serif}
.selection-action{display:grid;grid-template-columns:80px 1fr;width:100%;padding:9px;border:0;background:transparent;color:#20232a;text-align:left;cursor:pointer}.selection-action:hover{background:#f0eaf6}.selection-action strong{color:#5b2a86}.selection-action:nth-child(2) strong{color:#147d75}.selection-action:nth-child(3) strong{color:#d95f45}.selection-action:nth-child(4) strong{color:#5b2a86}.selection-action small{color:#777b84}
.custom-ask{display:none;padding:8px}.custom-ask textarea{width:100%;height:74px;padding:8px;border:1px solid #cbb8dc;background:#fcfcfd;color:#20232a;resize:none}.custom-send{width:100%;height:34px;margin-top:6px;border:0;background:#5b2a86;color:white;cursor:pointer}
#model-menu{position:fixed;z-index:45;display:none;width:246px;max-height:360px;overflow:auto;border:1px solid #cbb8dc;background:white;box-shadow:0 16px 38px rgba(50,33,63,.18);font-family:"Segoe UI",sans-serif}.model-head{padding:8px 10px;border-bottom:1px solid #e1e2e6;color:#686c75;font-size:12px}.model-option{display:flex;justify-content:space-between;width:100%;padding:9px 10px;border:0;background:transparent;color:#20232a;text-align:left;cursor:pointer}.model-option:hover,.model-option.is-current{background:#f0eaf6}.model-option small{color:#777b84}
@media(max-width:1150px){#study-workspace{grid-template-columns:230px minmax(500px,1fr)}#reader-resizer,#study-canvas{display:none}}@media(max-width:760px){#study-workspace{grid-template-columns:1fr}#study-sidebar{display:none}#study-reader{border:0}}
"""
WORKSPACE_JS = """
export default function(component){
 const{data,parentElement,setTriggerValue}=component;
 const root=parentElement.querySelector('#study-workspace'),side=parentElement.querySelector('#study-sidebar'),reader=parentElement.querySelector('#study-reader'),canvas=parentElement.querySelector('#study-canvas'),resizer=parentElement.querySelector('#reader-resizer'),menu=parentElement.querySelector('#selection-menu'),modelMenu=parentElement.querySelector('#model-menu');
 const sections=data?.sections||[],models=data?.models||[],nodes=data?.nodes||[],highlights=data?.highlights||[];
 const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
 let selectedText='',dragState=null,resizingReader=false;
 const highlightList=highlights.length?`<div class="section-label">我的重点 · ${highlights.length}</div>${highlights.map(h=>`<button class="section-button" data-highlight-anchor="highlight-${h.id}">${esc(h.preview)}<span class="node-control" data-highlight-delete="${h.id}" title="删除标记">×</span></button>`).join('')}`:'';
 side.innerHTML=`<div class="side-top"><span>NJU Reader</span><span class="workspace-badge">${esc(data?.mode||'学习')}</span><button class="back-workspace" data-command="back" title="返回资料库">‹</button></div><div class="side-doc">${esc(data?.title||'资料')}</div><nav class="section-list"><div class="section-label">章节目录 · ${sections.length}</div>${sections.map((s,i)=>`<button class="section-button ${i===0?'is-active':''}" style="--depth:${Math.max(0,s.level-1)}" data-section="${esc(s.id)}">${esc(s.label)}</button>`).join('')}${highlightList}</nav><footer class="sidebar-footer"><button class="model-trigger" data-command="models"><span>${esc(data?.currentModel||'选择模型')}</span><span>⌃</span></button><div class="footer-tools"><span>${models.length} 个模型</span><span>${nodes.length} 个画布节点</span></div></footer>`;
 reader.innerHTML=data?.html||'<p>暂无可阅读内容。</p>';
 const contextHelp={selection:'只发送划选文字',paragraph:'发送当前与相邻段落',section:'发送当前完整章节',rag:'检索全文相关片段',document:'发送整份资料'};
 const nodeHtml=nodes.map(node=>`<article class="canvas-node" data-node-id="${node.id}" data-node-type="${node.type}" style="left:${node.x}px;top:${node.y}px;width:${node.width}px;height:${node.height}px"><header class="node-title"><span>${esc(node.title)}</span><span class="node-badge">${node.type==='mindmap'?'MAP':'AI'}</span><button class="node-control" data-node-action="edit" title="编辑">✎</button><button class="node-control" data-node-action="delete" title="关闭并删除">×</button></header><div class="node-body">${node.selectedText?`<div class="node-selection">${esc(node.selectedText)}</div>`:''}${node.html}</div><div class="node-editor"><textarea>${esc(node.content)}</textarea><button data-node-action="save">保存修改</button></div></article>`).join('');
 canvas.innerHTML=`<div class="canvas-bar"><span class="context-help"></span><select id="context-select" title="控制发送给模型的资料范围"><option value="selection">仅选区</option><option value="paragraph">附近段落</option><option value="section">当前章节</option><option value="rag">文内检索</option><option value="document">整份资料</option></select><button class="canvas-tool" data-tool="mindmap">思维导图</button>${data?.isPaper?'<button class="canvas-tool" data-tool="paper_summary">5 分钟速读</button>':''}</div><div class="canvas-surface">${nodeHtml}</div>${nodes.length?'':'<div class="canvas-empty">划选原文或生成思维导图，内容会作为可编辑节点留在画布上</div>'}`;
 const contextSelect=canvas.querySelector('#context-select'),contextText=canvas.querySelector('.context-help'),surface=canvas.querySelector('.canvas-surface');contextSelect.value=data?.contextMode||'section';contextText.textContent=contextHelp[contextSelect.value];
 const resizeTimers=new Map(),sizeState=new Map();const nodeObserver=new ResizeObserver(entries=>entries.forEach(entry=>{const node=entry.target,key=`${node.offsetWidth}x${node.offsetHeight}`,previous=sizeState.get(node);sizeState.set(node,key);if(!previous||previous===key)return;clearTimeout(resizeTimers.get(node));resizeTimers.set(node,setTimeout(()=>sendLayout(node),350))}));surface.querySelectorAll('.canvas-node').forEach(node=>{sizeState.set(node,`${node.offsetWidth}x${node.offsetHeight}`);nodeObserver.observe(node)});
 menu.innerHTML=`<button class="selection-action" data-action="explain"><strong>解释</strong><small>拆解选中内容的直觉与步骤</small></button><button class="selection-action" data-action="example"><strong>举例</strong><small>给一个具体、可验证的例子</small></button><button class="selection-action" data-action="solve"><strong>解题</strong><small>按步骤完成选中的题目</small></button><button class="selection-action" data-action="highlight"><strong>标记</strong><small>保存为这份资料的长期重点</small></button><button class="selection-action" data-action="custom"><strong>自定义</strong><small>带着当前选区自由提问</small></button><div class="custom-ask"><textarea placeholder="关于这段原文，你还想问什么？"></textarea><button class="custom-send">发送提问</button></div>`;
 modelMenu.innerHTML=`<div class="model-head">模型选择</div>${models.length?models.map(m=>`<button class="model-option ${m.current?'is-current':''}" data-model="${m.id}"><span>${esc(m.label)}</span><small>${m.current?'当前':'切换'}</small></button>`).join(''):'<div class="model-head">尚未添加模型</div>'}<button class="model-option" data-command="subscription"><span>管理模型与订阅</span><small>打开</small></button>`;
 const savedWidth=Number(localStorage.getItem(`nju-reader-width-${data?.documentId}`));if(savedWidth>=420)root.style.setProperty('--reader-width',`${savedWidth}px`);
 const rootSelection=()=>parentElement.getSelection?parentElement.getSelection():window.getSelection();
 const sendLayout=node=>setTriggerValue('node_event',{action:'layout',node_type:node.dataset.nodeType,id:Number(node.dataset.nodeId),x:Math.round(node.offsetLeft),y:Math.round(node.offsetTop),width:Math.round(node.offsetWidth),height:Math.round(node.offsetHeight),nonce:Date.now()});
 const onSelection=()=>{const selection=rootSelection();selectedText=selection?.toString().trim()||'';if(!selectedText||!selection.rangeCount){menu.style.display='none';return}const rect=selection.getRangeAt(0).getBoundingClientRect();menu.style.left=`${Math.max(8,Math.min(rect.left,window.innerWidth-335))}px`;menu.style.top=`${Math.max(8,Math.min(rect.bottom+7,window.innerHeight-310))}px`;menu.style.display='block';menu.querySelector('.custom-ask').style.display='none';menu.querySelectorAll('.selection-action').forEach(x=>x.style.display='grid')};
 const onClick=e=>{const section=e.target.closest('[data-section]');if(section){reader.querySelector(`#${CSS.escape(section.dataset.section)}`)?.scrollIntoView({behavior:'smooth'});return}const anchor=e.target.closest('[data-highlight-anchor]');if(anchor&&!e.target.closest('[data-highlight-delete]')){reader.querySelector(`#${CSS.escape(anchor.dataset.highlightAnchor)}`)?.scrollIntoView({behavior:'smooth',block:'center'});return}const deleteHighlight=e.target.closest('[data-highlight-delete]')?.dataset.highlightDelete;if(deleteHighlight){setTriggerValue('highlight_event',{action:'delete',id:Number(deleteHighlight),nonce:Date.now()});return}const command=e.target.closest('[data-command]')?.dataset.command;if(command==='back'||command==='subscription')setTriggerValue('command',{name:command,nonce:Date.now()});if(command==='models'){const r=e.target.closest('[data-command]').getBoundingClientRect();modelMenu.style.left=`${r.left}px`;modelMenu.style.bottom=`${window.innerHeight-r.top+4}px`;modelMenu.style.display=modelMenu.style.display==='block'?'none':'block'}const action=e.target.closest('[data-action]')?.dataset.action;if(action==='custom'){menu.querySelectorAll('.selection-action').forEach(x=>x.style.display='none');menu.querySelector('.custom-ask').style.display='block';menu.querySelector('textarea').focus()}else if(action){setTriggerValue('action',{action,selected_text:selectedText,nonce:Date.now()});menu.style.display='none'}const model=e.target.closest('[data-model]')?.dataset.model;if(model)setTriggerValue('model',{id:Number(model),nonce:Date.now()});const tool=e.target.closest('[data-tool]')?.dataset.tool;if(tool)setTriggerValue('tool',{name:tool,nonce:Date.now()});const control=e.target.closest('[data-node-action]');if(control){const node=control.closest('.canvas-node'),kind=control.dataset.nodeAction;if(kind==='delete')setTriggerValue('node_event',{action:'delete',node_type:node.dataset.nodeType,id:Number(node.dataset.nodeId),nonce:Date.now()});if(kind==='edit'){node.querySelector('.node-body').style.display='none';node.querySelector('.node-editor').style.display='block'}if(kind==='save'){setTriggerValue('node_event',{action:'save',node_type:node.dataset.nodeType,id:Number(node.dataset.nodeId),content:node.querySelector('textarea').value,nonce:Date.now()})}}};
 const onPointerDown=e=>{if(e.target===resizer){resizingReader=true;resizer.classList.add('is-dragging');e.preventDefault();return}const header=e.target.closest('.node-title');if(!header||e.target.closest('.node-control'))return;const node=header.closest('.canvas-node');dragState={node,startX:e.clientX,startY:e.clientY,left:node.offsetLeft,top:node.offsetTop};e.preventDefault()};
 const onPointerMove=e=>{if(resizingReader){const sideWidth=side.offsetWidth,max=Math.max(420,window.innerWidth-sideWidth-330);root.style.setProperty('--reader-width',`${Math.max(420,Math.min(max,e.clientX-sideWidth))}px`);return}if(!dragState)return;const maxX=Math.max(0,surface.scrollWidth-dragState.node.offsetWidth),maxY=Math.max(0,surface.scrollHeight-dragState.node.offsetHeight);dragState.node.style.left=`${Math.max(0,Math.min(maxX,dragState.left+e.clientX-dragState.startX))}px`;dragState.node.style.top=`${Math.max(0,Math.min(maxY,dragState.top+e.clientY-dragState.startY))}px`};
 const onPointerUp=e=>{if(resizingReader){resizingReader=false;resizer.classList.remove('is-dragging');const width=Math.round(reader.offsetWidth);localStorage.setItem(`nju-reader-width-${data?.documentId}`,String(width));return}if(dragState){sendLayout(dragState.node);dragState=null;return}const node=e.target.closest?.('.canvas-node');if(node&&e.target===node)sendLayout(node)};
 const onSend=()=>{const q=menu.querySelector('textarea').value.trim();if(q)setTriggerValue('action',{action:'question',selected_text:selectedText,custom_question:q,nonce:Date.now()})};
 const onContext=e=>{contextText.textContent=contextHelp[e.target.value];setTriggerValue('context',{value:e.target.value,nonce:Date.now()})};
 reader.addEventListener('mouseup',onSelection);root.addEventListener('click',onClick);root.addEventListener('pointerdown',onPointerDown);parentElement.addEventListener('pointermove',onPointerMove);parentElement.addEventListener('pointerup',onPointerUp);menu.addEventListener('mousedown',e=>e.preventDefault());menu.addEventListener('click',onClick);menu.querySelector('.custom-send').addEventListener('click',onSend);modelMenu.addEventListener('click',onClick);contextSelect.addEventListener('change',onContext);
 return()=>{reader.removeEventListener('mouseup',onSelection);root.removeEventListener('click',onClick);root.removeEventListener('pointerdown',onPointerDown);parentElement.removeEventListener('pointermove',onPointerMove);parentElement.removeEventListener('pointerup',onPointerUp);menu.removeEventListener('click',onClick);modelMenu.removeEventListener('click',onClick);contextSelect.removeEventListener('change',onContext);nodeObserver.disconnect();resizeTimers.forEach(timer=>clearTimeout(timer))};
}
"""


_hall = st.components.v2.component("nju_library_hall", html=HALL_HTML, css=HALL_CSS, js=HALL_JS)
_collection = st.components.v2.component("nju_library_collection", html=COLLECTION_HTML, css=COLLECTION_CSS, js=COLLECTION_JS)
_workspace = st.components.v2.component("nju_study_workspace", html=WORKSPACE_HTML, css=WORKSPACE_CSS, js=WORKSPACE_JS)


def render_library_hall(categories: list[dict]):
    return _hall(data={"categories": categories}, height=820, on_open_change=lambda: None).open


def render_collection(categories: list[dict], documents: list[dict], active: str, title: str):
    result = _collection(
        data={"categories": categories, "documents": documents, "active": active, "title": title},
        height=820,
        on_command_change=lambda: None,
        on_category_change=lambda: None,
        on_open_document_change=lambda: None,
        on_reprocess_document_change=lambda: None,
    )
    return result


def _markdown_with_math(source: str) -> str:
    math_tokens: dict[str, str] = {}

    def replace_math(match: re.Match, display: str) -> str:
        expression = match.group(1).strip()
        token = f"NJUMATHTOKEN{len(math_tokens)}END"
        try:
            mathml = latex_to_mathml(expression)
            math_tokens[token] = f'<span class="math-block">{mathml}</span>' if display == "block" else mathml
        except Exception:
            math_tokens[token] = f"<code>{html_lib.escape(expression)}</code>"
        return token

    protected = re.sub(r"\$\$(.+?)\$\$", lambda match: replace_math(match, "block"), source or "", flags=re.DOTALL)
    protected = re.sub(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$", lambda match: replace_math(match, "inline"), protected, flags=re.DOTALL)
    rendered = markdown.markdown(
        protected,
        extensions=["extra", "fenced_code", "tables", "sane_lists", "toc"],
        output_format="html5",
    )
    for token, mathml in math_tokens.items():
        rendered = rendered.replace(token, mathml)
    return rendered


def _reader_html(source: str, highlights: list[dict]) -> tuple[str, list[dict]]:
    rendered = _markdown_with_math(source)
    sections = []
    for level, section_id, label in re.findall(r'<h([1-3]) id="([^"]+)">(.*?)</h\1>', rendered, flags=re.DOTALL):
        clean_label = re.sub(r"<[^>]+>", "", label)
        sections.append({"id": section_id, "label": html_lib.unescape(clean_label), "level": int(level)})
    if not sections:
        sections = [{"id": "document-start", "label": "00_原文", "level": 1}]
        rendered = f'<span id="document-start"></span>{rendered}'
    for highlight in highlights:
        selected = html_lib.escape(highlight.get("selected_text") or "")
        if selected and selected in rendered:
            rendered = rendered.replace(
                selected,
                f'<mark id="highlight-{int(highlight["id"])}">{selected}</mark>',
                1,
            )
    return rendered, sections


def render_study_workspace(
    *,
    title: str,
    markdown_source: str,
    models: list[dict],
    current_model: str,
    nodes: list[dict],
    highlights: list[dict],
    context_mode: str,
    is_paper: bool,
    document_id: int,
):
    reader_html, sections = _reader_html(markdown_source, highlights)
    rendered_nodes = [
        {
            **node,
            "html": _markdown_with_math(node.get("content") or ""),
        }
        for node in nodes
    ]
    highlight_data = [
        {
            "id": item["id"],
            "preview": re.sub(r"\s+", " ", item.get("selected_text") or "")[:32],
        }
        for item in highlights
    ]
    return _workspace(
        data={
            "title": title,
            "html": reader_html,
            "sections": sections,
            "models": models,
            "currentModel": current_model,
            "nodes": rendered_nodes,
            "highlights": highlight_data,
            "contextMode": context_mode,
            "isPaper": is_paper,
            "mode": "论文研读" if is_paper else "学习",
            "documentId": document_id,
        },
        height="content",
        on_command_change=lambda: None,
        on_action_change=lambda: None,
        on_model_change=lambda: None,
        on_context_change=lambda: None,
        on_tool_change=lambda: None,
        on_node_event_change=lambda: None,
        on_highlight_event_change=lambda: None,
    )
