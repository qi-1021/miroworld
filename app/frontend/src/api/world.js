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
    // 注意：不要手动设置 Content-Type，让浏览器自动生成带 boundary 的 multipart 头，
    // 否则后端无法解析上传的文件（历史 bug：首页上传的文件到世界设定页消失）
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
 * @param {String} projectId
 * @param {Object} data - { query, source?, limit?, semantic? }，semantic 为 true 时启用 bge-m3 语义向量检索
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
 * @param {Object} data - { total_steps?, time_step_minutes?, goal? }
 */
export function startWorldSimulation(projectId, data = {}) {
  return service({
    url: `/api/world/${projectId}/simulate`,
    method: 'post',
    data
  })
}

/**
 * 构建世界知识图谱（LLM 本体 + Graphiti/Neo4j，后台任务）
 * @param {String} projectId
 * @param {Object} data - { goal?, force?, chunk_size?, chunk_overlap? }
 * @returns {Promise} { success, task_id, graph_id }
 */
export function buildWorldGraph(projectId, data = {}) {
  return service({
    url: `/api/world/${projectId}/graph/build`,
    method: 'post',
    data
  })
}

/**
 * 读取世界知识图谱数据（节点/边/统计）
 * @param {String} projectId
 * @returns {Promise} { success, graph: { nodes, edges, node_count, edge_count }, graph_id }
 */
export function getWorldGraph(projectId) {
  return service({
    url: `/api/world/${projectId}/graph`,
    method: 'get'
  })
}
/**
 * 补边：为已有世界图谱补充缺失的关联边（异步任务）
 * @param {String} projectId
 * @param {Object} [data] - { force? }（可选，预留）
 * @returns {Promise} { success, task_id | message, ... }
 */
export function refillWorldGraphEdges(projectId, data = {}) {
  return service({
    url: `/api/world/${projectId}/graph/refill_edges`,
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

/**
 * 控制世界模拟（暂停/恢复/停止/采访）
 * @param {String} projectId
 * @param {String} simulationId
 * @param {Object} data - { action: 'pause'|'resume'|'stop'|'interview', character_name?, prompt? }
 */
export function controlWorldSimulation(projectId, simulationId, data) {
  return service({
    url: `/api/world/${projectId}/simulation/${simulationId}/control`,
    method: 'post',
    data,
    timeout: 90000 // 采访需等待子进程响应
  })
}

/**
 * 基于已有模拟做 what-if 分支推演
 * @param {String} projectId
 * @param {Object} data - { base_simulation_id, question, steps? }
 */
export function simulateWorldWhatIf(projectId, data) {
  return service({
    url: `/api/world/${projectId}/simulate/whatif`,
    method: 'post',
    data
  })
}

/**
 * 生成世界模拟报告（编年史/推演报告）
 * @param {String} projectId
 * @param {String} simulationId
 */
export function generateWorldReport(projectId, simulationId) {
  return service({
    url: `/api/world/${projectId}/report`,
    method: 'post',
    data: { simulation_id: simulationId },
    timeout: 300000 // 报告生成可能较慢
  })
}

/**
 * 读取已生成的世界报告
 * @param {String} projectId
 * @param {String} simulationId
 */
export function getWorldReport(projectId, simulationId) {
  return service({
    url: `/api/world/${projectId}/report/${simulationId}`,
    method: 'get'
  })
}
