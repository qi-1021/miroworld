/**
 * 临时存储待上传的文件和需求
 * 用于首页点击启动引擎后立即跳转，在Process页面再进行API调用
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  // 任务目标（必填）：一句话描述要推演/分析的目标
  simulationRequirement: '',
  // 附加说明（可选）：更详细的上下文/约束
  additionalContext: '',
  isPending: false
})

export function setPendingUpload(files, requirement, additionalContext = '') {
  state.files = files
  state.simulationRequirement = requirement
  state.additionalContext = additionalContext
  state.isPending = true
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    additionalContext: state.additionalContext,
    isPending: state.isPending
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.additionalContext = ''
  state.isPending = false
}

export default state
