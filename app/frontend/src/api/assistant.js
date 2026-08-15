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
