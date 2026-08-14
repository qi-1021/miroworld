import service, { requestWithRetry } from './index'

/**
 * 提交世界输入（背景文档/小说正文，至少一个）
 * @param {String} projectId
 * @param {Object} data - { background, story, chunk_size?, chunk_overlap?, metadata? }
 */
export function saveWorldInput(projectId, data) {
  return service({
    url: `/api/world/${projectId}/input`,
    method: 'post',
    data
  })
}

/**
 * 提交世界输入（multipart 多文件上传）
 * @param {String} projectId
 * @param {FormData} formData - background_files[] / story_files[] / background_text / story_text
 */
export function saveWorldInputMultipart(projectId, formData) {
  return service({
    url: `/api/world/${projectId}/input`,
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 600000 // 大文件解析可能较慢
  })
}

/**
 * 查询设定库统计
 */
export function getWorldSettings(projectId) {
  return service({
    url: `/api/world/${projectId}/settings`,
    method: 'get'
  })
}

/**
 * 列出设定库分块
 */
export function getWorldChunks(projectId, params = {}) {
  return service({
    url: `/api/world/${projectId}/chunks`,
    method: 'get',
    params
  })
}

/**
 * 按需检索设定块
 */
export function searchWorld(projectId, data) {
  return service({
    url: `/api/world/${projectId}/search`,
    method: 'post',
    data
  })
}

/**
 * 启动冲突检测（异步任务）
 */
export function detectWorldConflicts(projectId) {
  return requestWithRetry(() =>
    service({
      url: `/api/world/${projectId}/conflicts/detect`,
      method: 'post'
    })
  )
}

/**
 * 获取冲突检测报告
 */
export function getWorldConflicts(projectId) {
  return service({
    url: `/api/world/${projectId}/conflicts`,
    method: 'get'
  })
}

/**
 * 更新冲突处理状态
 * @param {String} projectId
 * @param {String} conflictId
 * @param {String} status - open | accepted | dismissed
 */
export function updateConflictStatus(projectId, conflictId, status) {
  return service({
    url: `/api/world/${projectId}/conflicts/${conflictId}`,
    method: 'patch',
    data: { status }
  })
}

/**
 * 删除项目的世界设定库
 */
export function deleteWorldData(projectId) {
  return service({
    url: `/api/world/${projectId}`,
    method: 'delete'
  })
}

// ==================== 世界模拟（独立模式） ====================

/**
 * 启动世界模拟
 * @param {String} projectId
 * @param {Object} data - { total_steps?, time_step_minutes? }
 */
export function startWorldSimulation(projectId, data = {}) {
  return service({
    url: `/api/world/${projectId}/simulate`,
    method: 'post',
    data
  })
}

/**
 * 列出项目的世界模拟记录
 */
export function listWorldSimulations(projectId) {
  return service({
    url: `/api/world/${projectId}/simulations`,
    method: 'get'
  })
}

/**
 * 查询单个世界模拟的状态与结果
 */
export function getWorldSimulation(projectId, simulationId) {
  return service({
    url: `/api/world/${projectId}/simulation/${simulationId}`,
    method: 'get'
  })
}
