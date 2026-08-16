import service from './index'

/**
 * 触发时间线抽取（异步任务）
 * @param {Object} data - { project_id, source: 'story'|'bg', timeline_type?: 'linear'|'parallel'|'tree'|'network'|'meta'|'auto' }
 * @returns {Promise} { success, data: { task_id } }
 */
export function extractTimeline(data) {
  return service({
    url: '/api/timeline/extract',
    method: 'post',
    data
  })
}

/**
 * 查询抽取任务进度
 * @param {String} taskId
 * @returns {Promise} { success, data: { status, total_chunks, done_chunks, llm_ok, heuristic, message } }
 */
export function getTimelineStatus(taskId) {
  return service({
    url: '/api/timeline/status',
    method: 'get',
    params: { task_id: taskId }
  })
}

/**
 * 获取项目的某条时间线事件列表
 * @param {String} projectId
 * @param {String} source - 'story' | 'bg'
 * @returns {Promise} { success, data: { events }, count }（sort_lower 升序）
 */
export function getTimeline(projectId, source) {
  return service({
    url: '/api/timeline/' + projectId,
    method: 'get',
    params: { source }
  })
}

/**
 * 获取时间线整体结构类型判断结果（single/parallel/tree/network/meta/mixed，可能为 null）
 * @param {String} projectId
 * @returns {Promise} { success, data: { project_id, structure: { type, confidence, reason, strategy } | null } }
 */
export function getTimelineStructure(projectId) {
  return service({
    url: '/api/timeline/' + projectId + '/structure',
    method: 'get'
  })
}

/**
 * 人工修正单个事件
 * @param {String} projectId
 * @param {String} eventId
 * @param {Object} patch - { summary?, age?, sort_lower?, ... }
 * @returns {Promise} { success, data: 更新后事件 }
 */
export function updateTimelineEvent(projectId, eventId, patch) {
  return service({
    url: '/api/timeline/' + projectId + '/' + eventId,
    method: 'patch',
    data: patch
  })
}

/**
 * 基于世界目标做未来推演（kind='future'）
 * @param {Object} data - { project_id, goal, horizon? }
 * @returns {Promise} { success, data: { task_id } }
 */
export function generateTimelineFuture(data) {
  return service({
    url: '/api/timeline/future',
    method: 'post',
    data
  })
}

/**
 * 在某个历史事件点分叉做未来推演（异步任务）
 * @param {Object} data - { project_id, event_id, goal, horizon? }
 * @returns {Promise} { success, data: { task_id } }
 */
export function generateTimelineFork(data) {
  return service({
    url: '/api/timeline/fork',
    method: 'post',
    data
  })
}

/**
 * 对某个事件提交异议（事件归属/分类/时间/地点等）
 * @param {String} projectId
 * @param {String} eventId
 * @param {Object} data - { category, reason, suggestion? }
 * @returns {Promise} { success, data: 事件（含新 objections） }
 */
export function submitTimelineObjection(projectId, eventId, data) {
  return service({
    url: '/api/timeline/' + projectId + '/' + eventId + '/objection',
    method: 'post',
    data
  })
}

/**
 * 对正在运行的分叉任务补充设定（guide）
 * @param {String} taskId
 * @param {String} guidance
 * @returns {Promise} { success, data: { accepted } }；已结束→400，任务不存在→404
 */
export function submitForkGuidance(taskId, guidance) {
  return service({
    url: '/api/timeline/fork/guidance',
    method: 'post',
    data: { task_id: taskId, guidance }
  })
}

/**
 * 在某个分支上继续补充设定续推（新异步任务）
 * @param {String} projectId
 * @param {String} branchId
 * @param {String} guidance
 * @param {Number} [horizon]
 * @returns {Promise} { success, data: { task_id } }
 */
export function continueBranch(projectId, branchId, guidance, horizon) {
  return service({
    url: '/api/timeline/' + projectId + '/branch/continue',
    method: 'post',
    data: { branch_id: branchId, guidance, horizon: horizon != null ? horizon : undefined }
  })
}

/**
 * 获取项目的人物设定档案（空档案自动从事件种子）
 * @param {String} projectId
 * @returns {Promise} { success, data: { characters }, count }
 */
export function getTimelineCharacters(projectId) {
  return service({
    url: '/api/timeline/' + projectId + '/characters',
    method: 'get'
  })
}

/**
 * 保存项目的人物设定档案（全量覆盖）
 * @param {String} projectId
 * @param {Array} characters - [{ name, traits, description }]
 * @returns {Promise} { success, data: ... }
 */
export function saveTimelineCharacters(projectId, characters) {
  return service({
    url: '/api/timeline/' + projectId + '/characters',
    method: 'put',
    data: { characters }
  })
}

/**
 * 对比某分支与主线的事件差异
 * @param {String} projectId
 * @param {String} branchId
 * @returns {Promise} { success, data: { branch_id, branch_point_id, branch_point_summary, entries:[...] }, count }
 *   entries[].kind: 'before'|'base_only'|'branch_new'|'changed'
 */
export function getBranchCompare(projectId, branchId) {
  return service({
    url: '/api/timeline/' + projectId + '/branch/compare',
    method: 'get',
    params: { branch_id: branchId }
  })
}

/**
 * 删除单个事件
 * @param {String} projectId
 * @param {String} eventId
 * @returns {Promise} { success, data: { deleted: true } }；404 不存在
 */
export function deleteTimelineEvent(projectId, eventId) {
  return service({
    url: '/api/timeline/' + projectId + '/' + eventId,
    method: 'delete'
  })
}

/**
 * 将多个事件合并到目标事件
 * @param {String} projectId
 * @param {String} targetId
 * @param {Array} sourceIds - 待合并源事件 id 列表（非空）
 * @returns {Promise} { success, data: 合并后事件 }
 */
export function mergeTimelineEvents(projectId, targetId, sourceIds) {
  return service({
    url: '/api/timeline/' + projectId + '/merge',
    method: 'post',
    data: { target_id: targetId, source_ids: sourceIds }
  })
}

/**
 * 批量操作时间线事件（删除 / 批量更新）
 * @param {String} projectId
 * @param {Object} payload - { action: 'delete'|'update', event_ids: [], patch?: {} }
 * @returns {Promise} { success, data: { action, deleted, updated } }
 */
export function batchTimelineEvents(projectId, payload) {
  return service({
    url: '/api/timeline/' + projectId + '/batch',
    method: 'post',
    data: payload
  })
}

/**
 * 一键生成人物设定初稿（后台任务，复用 /api/timeline/status 轮询）
 * @param {String} projectId
 * @returns {Promise} { success, data: { task_id } }
 */
export function generateTimelineCharacters(projectId) {
  return service({
    url: '/api/timeline/' + projectId + '/characters/generate',
    method: 'post'
  })
}

/**
 * 获取背景时间线线索清单（第一遍识别结果）
 * @param {String} projectId
 * @returns {Promise} { success, data: { threads }, count }
 */
export function getTimelineThreads(projectId) {
  return service({
    url: '/api/timeline/' + projectId + '/threads',
    method: 'get'
  })
}

/**
 * （重新）生成项目的最终时间线报告（小说/梗概，确定性聚合）
 * @param {String} projectId
 * @returns {Promise} { success, data: { project_id, generated_at, format, deterministic, goal, structure, best_flow, events_count, synopsis, novel } }
 */
export function generateFinalReport(projectId) {
  return service({
    url: '/api/timeline/' + projectId + '/final-report',
    method: 'post'
  })
}

/**
 * 读取已生成的项目最终时间线报告
 * @param {String} projectId
 * @returns {Promise} { success, data: { has_report, project_id, ... } }
 */
export function getFinalReport(projectId) {
  return service({
    url: '/api/timeline/' + projectId + '/final-report',
    method: 'get'
  })
}

/**
 * 构造最终时间线报告下载 URL
 * @param {String} projectId
 * @returns {String} 相对下载地址（供 window.open / <a download>）
 */
export function finalReportDownloadUrl(projectId) {
  return '/api/timeline/' + projectId + '/final-report/download'
}

/**
 * 时间线导出（研究用途）：选择单/多/全部线程，按时间顺序导成 md/json/csv。
 * @param {String} projectId
 * @param {Object} data - { source?, thread_keys?: string[], include_all_threads?: bool, format?: 'md'|'json'|'csv', include_meta?: bool }
 * @returns {Promise} { success, data: { filename, format, content, selected_threads, total_events, structure } }
 */
export function exportTimeline(projectId, data) {
  return service({
    url: '/api/timeline/' + projectId + '/export',
    method: 'post',
    data
  })
}

/**
 * 构造时间线导出直接下载 URL
 * @param {String} projectId
 * @param {Object} qs - { source?, format?, thread_keys? }
 * @returns {String} 相对下载地址（供 <a download>）
 */
export function timelineExportDownloadUrl(projectId, qs = {}) {
  const p = new URLSearchParams()
  if (qs.source) p.set('source', qs.source)
  if (qs.format) p.set('format', qs.format)
  if (qs.thread_keys && qs.thread_keys.length) p.set('thread_keys', qs.thread_keys.join(','))
  const qsStr = p.toString()
  return '/api/timeline/' + projectId + '/export/download' + (qsStr ? '?' + qsStr : '')
}
