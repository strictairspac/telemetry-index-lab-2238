import {PLAN_STATUSES,OPERATION_ACTIONS,OPERATION_STATUSES} from '../../constants/enums.js';import {esc} from '../../utils/html.js';
export const planStatus=s=>`<span class="status plan-${s}">${PLAN_STATUSES[s]||s}</span>`;
export const operationStatus=s=>`<span class="status plan-${s}">${OPERATION_STATUSES[s]||s}</span>`;
export const operationAction=s=>esc(OPERATION_ACTIONS[s]||s);
export const verifiedBadge=(v,current=true)=>v?`<span class="verified ${current?'':'stale'}">${current?'实体已核对':'核对已失效'}</span>`:'<span class="unverified">未核对</span>';
