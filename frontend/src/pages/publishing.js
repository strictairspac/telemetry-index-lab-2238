import {store} from '../stores/business.js';
import {esc,json} from '../utils/html.js';
import {table} from '../components/common/table.js';
import {planStatus,operationStatus,operationAction,verifiedBadge} from '../components/common/plan.js';

const planLabel=p=>`<b>#${p.id} ${esc(p.index_name||'待分配名称')}</b><small>试验 #${p.experiment_id} · ${esc(p.columns.join(' → '))}<br>快照 ${esc((p.snapshot_digest||'').slice(0,12))}…</small>`;

function planRows(){
 return store.plans.map(p=>{
  const actions=[];
  if(p.status==='pending')actions.push(`<button class="quiet" data-publish="${p.id}">发布</button>`);
  if(p.status==='active'&&p.previous_plan_id)actions.push(`<button class="quiet" data-rollback="${p.id}">回退到 #${p.previous_plan_id}</button>`);
  if(p.status==='conflict')actions.push('<small class="muted">需人工处理</small>');
  let state=planStatus(p.status);
  if(p.status==='active')state+=`<small>${verifiedBadge(p.verified,p.verification_current)}</small>`;
  else if(p.error)state+=`<small class="muted">${esc(p.error)}</small>`;
  return [planLabel(p),`<code>${esc(p.columns.join(' → '))}</code><small>前一生效 #${p.previous_plan_id??'—'}</small>`,state,`<span class="actions">${actions.join('')}</span>`];
 });
}

function activeRows(){
 return store.plans.filter(p=>p.status==='active').map(p=>{
  const live=(store.indexes?.indexes||[]).find(i=>i.index_name.toLowerCase()===(p.index_name||'').toLowerCase());
  const current=!!(live&&live.columns.join()===p.columns.join());
  return [`<b>${esc(p.index_name)}</b><small>负载 #${p.workload_id} · 方案 #${p.id}</small>`,`<code>${esc(p.columns.join(' → '))}</code>`,verifiedBadge(p.verified,current),`<small>${esc(p.activated_at||'')}</small>`];
 });
}

function entityRows(){
 return (store.indexes?.indexes||[]).map(i=>{
  const reg=store.indexes.active_by_index[i.index_name.toLowerCase()];
  const kind=i.classified==='resident'?'常驻':i.classified==='external'?'外部/手工':i.classified==='trial'?'试验临时':'主键';
  return [`<b>${esc(i.index_name)}</b>`,`<code>${esc(i.columns.join(' → '))}</code>`,`<span class="tag">${kind}</span>`,reg?`方案 #${reg.plan_id}${reg.verified?' · 已核对':' · 未核对'}`:'<span class="muted">未登记</span>'];
 });
}

function operationRows(){
 return store.operations.slice(0,30).map(o=>{
  const retry=o.status==='failed'?`<button class="quiet" data-retry="${o.id}">重试同一操作</button>`:o.status==='conflict'?'<small class="muted">冲突未覆盖现场，需人工处理后另建方案</small>':'';
  return [`<b>#${o.id} ${operationAction(o.action)}</b><small>${esc(o.actor)}</small>`,`方案 #${o.plan_id??'—'}<small>${esc(o.index_name||'—')}</small>`,operationStatus(o.status),`<small>${esc(o.finished_at||o.created_at||'')}${o.error?'<br>'+esc(o.error):''}</small>${retry}`];
 });
}

export function publishingPage(){
 const published=store.experiments.filter(e=>e.status==='completed'&&e.result&&e.result.equal_results);
 const openOptions=published.map(e=>`<option value="${e.id}">#${e.id} ${esc(e.name)} · ${esc((e.snapshot?.candidate?.columns||[]).join(' → '))}</option>`).join('');
 return `<div class="split">
  <section>
   <h2>从试验快照发布常驻索引</h2>
   <p>只有已完成且结果等价的试验才能发布。发布时复制试验快照的列定义，候选之后修改不影响方案；真正改变遥测表索引并核对实体后才报告成功。</p>
   <form id="plan-form">
    <label>来源试验（仅已完成且结果等价）<select name="experiment_id">${openOptions||'<option value="">暂无可发布试验</option>'}</select></label>
    <label>常驻索引名称（可留空自动生成）<input name="index_name" placeholder="idx_live_wl_17_shift"></label>
    <small>小写字母、数字、下划线；不能使用试验临时前缀 trial_ev_。同名异定义会被拒绝并保留现场。</small>
    <button type="submit" ${published.length?'':'disabled'}>创建发布方案 →</button>
   </form>
   <h3>待执行与历史方案</h3>
   ${store.plans.length?table(['方案','列定义','状态','操作'],planRows()):'<div class="empty">尚无发布方案。完成一次等价试验后在这里创建。</div>'}
   <aside class="note">发布与回退共用试验串行锁；提交前会再次核对生效方案没有被其他操作改变，发现变化则整体拒绝、不改动现场。</aside>
  </section>
  <section>
   <h2>当前生效方案 <em>${store.plans.filter(p=>p.status==='active').length}</em></h2>
   ${store.plans.some(p=>p.status==='active')?table(['索引','列定义','实体核对','生效时间'],activeRows()):'<div class="empty">当前没有生效中的常驻索引。试验索引都是临时的，会在试验后删除。</div>'}
   <h3>遥测表实际索引实体</h3>
   <p class="muted">以下直接来自 information_schema.statistics，是发布、回退与清理的判断依据。</p>
   ${store.indexes?table(['索引','真实列序','类别','登记'],entityRows()):'<div class="empty">正在读取索引实体…</div>'}
   <h3>操作沿革</h3>
   ${store.operations.length?table(['操作','方案/索引','状态','时间与说明'],operationRows()):'<div class="empty">尚无发布或回退操作。</div>'}
   <details><summary>打开完整方案与操作原始记录</summary><pre>${json({plans:store.plans,operations:store.operations,indexes:store.indexes})}</pre></details>
  </section>
 </div>`;
}
