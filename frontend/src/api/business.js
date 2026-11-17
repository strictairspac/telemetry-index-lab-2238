import {api,post} from './client.js';
export const workloads={list:()=>api('/workloads'),save:(d,id)=>post('/workloads'+(id?'/'+id:''),d,id?'PUT':'POST')};
export const candidates={list:()=>api('/candidates'),save:(d,id)=>post('/candidates'+(id?'/'+id:''),d,id?'PUT':'POST')};
export const experiments={list:()=>api('/experiments'),run:d=>post('/experiments',d),detail:id=>api('/experiments/'+id)};
export const plans={
 list:()=>api('/index-plans'),
 operations:()=>api('/index-operations'),
 indexes:()=>api('/telemetry/indexes'),
 create:d=>post('/index-plans',d),
 publish:id=>post('/index-plans/'+id+'/publish',{}),
 rollback:id=>post('/index-plans/'+id+'/rollback',{}),
 retry:id=>post('/index-operations/'+id+'/retry',{})};
