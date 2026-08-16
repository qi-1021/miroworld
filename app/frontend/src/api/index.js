import axios from 'axios'
import i18n from '../i18n'

// 创建axios实例
// baseURL 默认留空（相对路径）：
// - 开发模式：Vite 代理 /api → localhost:5001（见 vite.config.js）
// - 生产模式：Flask 同源托管前端 dist，/api 直接命中
// - 手机隧道：浏览器访问的是公网域名，绝不能写死 localhost（否则手机访问会 network error）
const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 300000, // 5分钟超时（本体生成可能需要较长时间）
  // 注意：不要在此默认设置 Content-Type：
  // - 普通 JSON body 由 axios 自动加 application/json
  // - FormData（文件上传）由浏览器自动加 multipart/form-data; boundary=...，
  //   手动设置会丢失 boundary 导致后端解析不到文件（历史 bug）
})

// 请求拦截器
service.interceptors.request.use(
  config => {
    config.headers['Accept-Language'] = i18n.global.locale.value
    return config
  },
  error => {
    console.error('Request error:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器（容错重试机制）
service.interceptors.response.use(
  response => {
    const res = response.data

    // 如果返回的状态码不是success，则抛出错误
    if (!res.success && res.success !== undefined) {
      console.error('API Error:', res.error || res.message || 'Unknown error')
      return Promise.reject(new Error(res.error || res.message || 'Error'))
    }

    return res
  },
  error => {
    // 轻量提示，不阻断页面：视图层各自处理错误分支；这里仅记录一行摘要，
    // 避免后台轮询（状态查询/任务不存在 404 等）的高频失败刷屏完整堆栈。
    const status = error?.response?.status
    const url = error?.config?.url || ''
    if (status === 404) {
      console.warn(`[api] 404 ${url}`)
    } else if (error.code === 'ECONNABORTED' && error.message.includes('timeout')) {
      console.warn(`[api] timeout ${url}`)
    } else if (error.message === 'Network Error') {
      console.warn(`[api] network error ${url}`)
    } else if (status) {
      console.warn(`[api] ${status} ${url}`, error?.config?.method ? error.config.method.toUpperCase() : '')
    } else {
      console.warn(`[api] error ${url}:`, error?.message || error)
    }

    return Promise.reject(error)
  }
)

// 带重试的请求函数
export const requestWithRetry = async (requestFn, maxRetries = 3, delay = 1000) => {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await requestFn()
    } catch (error) {
      if (i === maxRetries - 1) throw error

      console.warn(`Request failed, retrying (${i + 1}/${maxRetries})...`)
      await new Promise(resolve => setTimeout(resolve, delay * Math.pow(2, i)))
    }
  }
}

export default service
