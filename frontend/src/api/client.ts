import axios from 'axios'
import { ElMessage } from 'element-plus'
import type { AxiosInstance, AxiosError } from 'axios'

const defaultBaseURL = import.meta.env.VITE_API_BASE_URL || '/api'

const client: AxiosInstance = axios.create({
  baseURL: defaultBaseURL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

client.interceptors.request.use(
  (config) => {
    const savedUrl = localStorage.getItem('apiUrl')
    const savedTimeout = localStorage.getItem('timeout')
    if (savedUrl) config.baseURL = savedUrl
    if (savedTimeout) config.timeout = Number(savedTimeout)
    return config
  },
  (error: AxiosError) => Promise.reject(error)
)

client.interceptors.response.use(
  (response) => {
    // Backend returns { code, message, data } format
    const body = response.data
    if (body && body.code !== undefined && body.data !== undefined) {
      return body
    }
    // Fallback: plain JSON response
    return body
  },
  (error: AxiosError) => {
    if (error.response) {
      const status = error.response.status
      const messages: Record<number, string> = {
        400: '请求参数错误',
        401: '未授权，请重新登录',
        403: '拒绝访问',
        404: '请求的资源不存在',
        500: '服务器内部错误',
        502: '网关错误',
        503: '服务不可用',
        504: '网关超时',
      }
      ElMessage.error(messages[status] || `请求失败 (${status})`)
    } else if (error.request) {
      ElMessage.error('网络连接失败，请检查网络')
    } else {
      ElMessage.error(error.message || '未知错误')
    }
    return Promise.reject(error)
  }
)

export default client