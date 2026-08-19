import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import i18n from './i18n'

// LGGC：纯 CSS 液态玻璃（GuoChen Wang, MIT）
import './assets/lggc/lggc.css'

const app = createApp(App)

app.use(router)
app.use(i18n)

// ============================================================
// 全局前端错误收集与报告入口
// - 缓冲区保留最近 20 条错误，供支持报告打包
// - 遇到未捕获错误时自动弹出友好的 ErrorReportDialog
// - 不干扰组件层自身的错误处理（error.value / try-catch 等）
// ============================================================
const MAX_ERROR_BUFFER = 20
const errorBuffer = []
// 上次自动弹出错误报告的时间戳（毫秒），用于 30 秒节流，避免后台轮询错误刷屏
let _lastAutoOpen = 0

function normalizeError(errorOrEvent) {
  const err = errorOrEvent instanceof Error
    ? errorOrEvent
    : new Error(String(errorOrEvent))
  return {
    timestamp: new Date().toISOString(),
    message: err.message || String(errorOrEvent),
    stack: err.stack || '',
    // 只记录来源页面（去 query/hash），避免 URL 中的 token 泄漏进错误报告
    url: window.location.origin + window.location.pathname
  }
}

function pushError(errorOrEvent) {
  const entry = normalizeError(errorOrEvent)
  // 双捕获去重：与缓冲区最后一条同消息、同堆栈且 2 秒内到达时视为重复，跳过
  const last = errorBuffer[errorBuffer.length - 1]
  if (last) {
    const lastTime = new Date(last.timestamp).getTime()
    const isDuplicate = (
      last.message === entry.message &&
      last.stack === entry.stack &&
      Date.now() - lastTime < 2000
    )
    if (isDuplicate) return
  }
  errorBuffer.push(entry)
  if (errorBuffer.length > MAX_ERROR_BUFFER) {
    errorBuffer.shift()
  }
}

function showErrorReport() {
  // 30 秒内已自动弹过一次则静默跳过（错误仍已写入缓冲，仅不打扰用户）
  if (Date.now() - _lastAutoOpen < 30000) return
  _lastAutoOpen = Date.now()
  window.dispatchEvent(
    new CustomEvent('open-error-report', { detail: { triggeredByError: true } })
  )
}

app.config.errorHandler = (err) => {
  pushError(err)
  showErrorReport()
}

window.onerror = (message, _source, _lineno, _colno, error) => {
  pushError(error || message)
  showErrorReport()
}

window.addEventListener('unhandledrejection', (event) => {
  pushError(event.reason)
  showErrorReport()
})

window.getFrontendErrors = () => [...errorBuffer]
window.clearFrontendErrors = () => {
  errorBuffer.length = 0
}
window.openErrorReport = () => {
  window.dispatchEvent(
    new CustomEvent('open-error-report', { detail: { triggeredByError: false } })
  )
}

app.mount('#app')
