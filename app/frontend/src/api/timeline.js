import service from './index'

/**
 * 触发时间线抽取（异步任务）
 * @param {Object} data - { project_id, source: 'story'|'bg' }
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
