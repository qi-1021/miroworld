import service from './index'

/**
 * 向内置项目助手提问
 * @param {String} projectId
 * @param {String} question
 * @returns {Promise} { success, data: { answer, context } }
 */
export function askAssistant(projectId, question) {
  return service({
    url: '/api/assistant/ask',
    method: 'post',
    data: { project_id: projectId, question }
  })
}

/**
 * 直接让 Agent 执行一个已知动作（跳过 LLM 决策，用于快捷操作/工具调用）
 * @param {String} projectId
 * @param {String} action - 动作名，如 get_project_status / start_world_simulation
 * @param {Object} params - 动作参数
 * @returns {Promise} { success, data: { answer, action, action_result, context } }
 */
export function listAgentTasks() {
  return service({
    url: '/api/assistant/tasks',
    method: 'get'
  })
}

export function runAssistantAction(projectId, action, params = {}) {
  return service({
    url: '/api/assistant/ask',
    method: 'post',
    data: { project_id: projectId, direct_action: action, params }
  })
}
