import {JSDOM} from '/tmp/node_modules/jsdom/lib/api.js';
import fs from 'fs';
const root='/workspace/frontend/src';
const files={};
const walk=p=>{for(const f of fs.readdirSync(p,{withFileTypes:true})){const fp=p+'/'+f.name;if(f.isDirectory())walk(fp);else if(f.name.endsWith('.js'))files['/src'+fp.slice(root.length)]=fs.readFileSync(fp,'utf8');}};
walk(root);
const dom=new JSDOM('<!doctype html><div id="app"></div>',{url:'http://localhost/'});
global.window=dom.window;global.document=dom.window.document;global.sessionStorage=dom.window.sessionStorage;
const FIXTURES={'/auth/me':{email:'operator@index.local',role:'operator'},
 '/workloads':[{id:1,name:'泵站17温升排查',sensor_id:17,start_at:'2026-11-01T00:00:00',end_at:'2026-11-30T23:59:59',device_type:null,description:'d'}],
 '/candidates':[{id:1,name:'传感器17时间窗',workload_id:1,columns:['sensor_id','recorded_at'],note:''}],
 '/experiments':[{id:9,name:'shift-1',status:'completed',candidate_id:1,workload_id:1,result:{equal_results:true,prefix:{score:80,reason:['sensor_id: equality prefix +40'],formula:'formula'},rows:120,before_median_ms:3,after_median_ms:1,before_plan:[{type:'ALL',key:null,rows:5000}],after_plan:[{type:'range',key:'trial_ev_9',rows:120}],insert20_before_ms:1,insert20_after_ms:2,checksum:'abc',query:'SELECT 1',parameters:{},trial_index:'trial_ev_9',baseline:{resident_indexes:['idx_live_wl_1_p1'],external_indexes:[]}},snapshot:{candidate:{columns:['sensor_id','recorded_at']}}}],
 '/index-plans':[{id:3,index_name:'idx_live_wl_1_p3',experiment_id:9,workload_id:1,columns:['sensor_id','recorded_at'],status:'active',previous_plan_id:2,verified:true,verification_current:true,activated_at:'2026-11-17T10:00:00'}],
 '/index-operations':[{id:8,action:'publish',status:'completed',plan_id:3,index_name:'idx_live_wl_1_p3',actor:'operator@index.local',finished_at:'2026-11-17T10:00:00'},{id:9,action:'publish',status:'failed',plan_id:4,index_name:'idx_live_wl_x',actor:'operator@index.local',error:'等待锁超时，未改动任何索引'}],
 '/telemetry/indexes':{indexes:[{index_name:'PRIMARY',columns:['id'],classified:'primary'},{index_name:'idx_live_wl_1_p3',columns:['sensor_id','recorded_at'],classified:'resident'},{index_name:'ext_manual',columns:['value'],classified:'external'}],active_by_index:{idx_live_wl_1_p3:{plan_id:3,columns:['sensor_id','recorded_at'],verified:true}}}};
global.fetch=async u=>{const path=String(u).replace('/api','');return {ok:true,status:200,json:async()=>FIXTURES[path]??[]};};
const norm=(from,s)=>{if(!s.startsWith('.'))return null;const base=from.split('/').slice(0,-1);for(const x of s.split('/')){if(x==='..')base.pop();else if(x!=='.')base.push(x);}return base.join('/');};
const mods={};
async function loadMod(p){
 if(mods[p])return mods[p];
 let code=files[p];if(code===undefined)throw new Error('missing module '+p);
 const deps={};const names=[];
 code=code.replace(/import \{([^}]+)\} from '([^']+)';/g,(m,list,spec)=>{const target=norm(p,spec);if(!target)throw new Error('external import '+spec);const id='__dep'+Object.keys(deps).length;deps[id]=target;names.push([id,list]);return `const {${list.replace(/\s+/g,' ')}} = ${id};`;});
 code=code.replace(/^export const /gm,'const ').replace(/^export function /gm,'function ').replace(/^export async function /gm,'async function ').replace(/^export /gm,'');
 const exported=[...code.matchAll(/^(?:const|function|async function)\s+([A-Za-z0-9_$]+)/gm)].map(m=>m[1]);
 const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;const fn=new AsyncFunction(...Object.keys(deps),'document','window','sessionStorage','fetch',code+`\nreturn {${exported.map(n=>n+':'+n).join(',')}};`);
 const args=[];for(const id of Object.keys(deps))args.push(await loadMod(deps[id]));
 const api=await fn(...args,document,window,sessionStorage,fetch);
 mods[p]=api;return api;
}
document.defaultView.sessionStorage.setItem('token','x');await loadMod('/src/app.js');
await new Promise(r=>setTimeout(r,250));
const html=document.getElementById('app').innerHTML;
if(!/索引发布/.test(html))throw new Error('nav missing publishing');
const {publishingPage}=await loadMod('/src/pages/publishing.js');
const {store}=await loadMod('/src/stores/business.js');
const {plans,experiments}=await loadMod('/src/api/business.js');
store.plans=await plans.list();store.operations=await plans.operations();store.indexes=await plans.indexes();store.experiments=await experiments.list();store.workloads=[];store.candidates=[];
const page=publishingPage();
for(const must of ['发布常驻索引','idx_live_wl_1_p3','实体已核对','操作沿革','外部/手工','遥测表实际索引实体'])if(!page.includes(must))throw new Error('missing '+must);
if(!page.includes('回退到 #2'))throw new Error('rollback button missing');
if(!page.includes('data-retry="9"'))throw new Error('retry button missing');
if(!/执行失败/.test(page))throw new Error('operation status missing');
const {resultsPage}=await loadMod('/src/pages/results.js');
const rp=resultsPage(9);
if(!rp.includes('试验前后的常驻索引基线')||!rp.includes('用本次快照创建发布方案'))throw new Error('results page missing baseline/publish hint');
console.log('frontend render ok');

process.exit(0);
