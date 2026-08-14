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
