import {workloads,candidates,experiments,plans} from '../api/business.js';
export const store={workloads:[],candidates:[],experiments:[],plans:[],operations:[],indexes:null,user:null};
export async function refresh(){[store.workloads,store.candidates,store.experiments]=await Promise.all([workloads.list(),candidates.list(),experiments.list()]);await refreshPublishing();}
export async function refreshPublishing(){try{[store.plans,store.operations,store.indexes]=await Promise.all([plans.list(),plans.operations(),plans.indexes()]);}catch(e){store.plans=store.plans||[];store.operations=store.operations||[];}}
