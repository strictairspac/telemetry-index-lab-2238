export const ROLES={admin:'管理员',operator:'操作员',viewer:'观察员'};
export const STATUSES={queued:'等待执行',running:'试验中',completed:'已完成',failed:'执行失败'};
export const COLUMNS=['sensor_id','recorded_at','device_type','value'];
export const PLAN_STATUSES={pending:'待执行',active:'生效中',superseded:'已被替换',rolled_back:'已回退',conflict:'冲突待核',failed:'发布失败'};
export const OPERATION_ACTIONS={publish:'发布',rollback:'回退'};
export const OPERATION_STATUSES={pending:'排队中',running:'执行中',completed:'已完成',conflict:'冲突未生效',failed:'执行失败'};
