import service, { requestWithRetry } from './index'

/**
 * 创建空项目（世界模拟等独立模式的入口容器）
 * @param {Object} data - { project_name: String }
 * @returns {Promise} 返回 { success, data: { project_id } }
 */
export function createProject(data) {
  return service({
    url: '/api/graph/project',
    method: 'post',
    data
  })
}

/**
 * 生成本体（上传文档和模拟需求）
 * @param {Object} data - 包含files, simulation_requirement, project_name等
 * @returns {Promise}
 */
export function generateOntology(formData) {
  return requestWithRetry(() =>
    service({
      url: '/api/graph/ontology/generate',
      method: 'post',
      data: formData,
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
  )
}

/**
 * 构建图谱
 * @param {Object} data - 包含project_id, graph_name等
 * @returns {Promise}
 */
export function buildGraph(data) {
  return requestWithRetry(() =>
    service({
      url: '/api/graph/build',
      method: 'post',
      data
    })
  )
}

/**
 * 查询任务状态
 * @param {String} taskId - 任务ID
 * @returns {Promise}
 */
export function getTaskStatus(taskId) {
  return service({
    url: `/api/graph/task/${taskId}`,
    method: 'get'
  })
}

/**
 * 获取图谱数据
 * @param {String} graphId - 图谱ID
 * @returns {Promise}
 */
export function getGraphData(graphId) {
  return service({
    url: `/api/graph/data/${graphId}`,
    method: 'get'
  })
}

/**
 * 获取项目信息
 * @param {String} projectId - 项目ID
 * @returns {Promise}
 */
export function getProject(projectId) {
  return service({
    url: `/api/graph/project/${projectId}`,
    method: 'get'
  })
}

/**
 * 删除项目
 * @param {String} projectId - 项目ID
 * @returns {Promise} { success, message }
 */
export function deleteProject(projectId) {
  return service({
    url: `/api/graph/project/${projectId}`,
    method: 'delete'
  })
}

/**
 * 重置项目状态（用于重新构建图谱）
 * @param {String} projectId - 项目ID
 * @returns {Promise} { success, message, data }
 */
export function resetProject(projectId) {
  return service({
    url: `/api/graph/project/${projectId}/reset`,
    method: 'post'
  })
}
