import axios from 'axios'

const api = axios.create({
  baseURL: '',
  withCredentials: true,
  timeout: 300000, // 5 分钟超时（视频生成可能很慢）
})

// 响应拦截器
api.interceptors.response.use(
  (response) => response,
  (error) => {
    return Promise.reject(error)
  }
)

// ── PPT Upload ──
export const uploadPPT = (file, onProgress) => {
  const formData = new FormData()
  formData.append('file', file)
  return api.post('/api/outline', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: (e) => onProgress?.(Math.round((e.loaded * 100) / e.total)),
  })
}

// ── Script Generation ──
export const generateScript = (params) => api.post('/api/generate-script', params)
export const generateScriptList = (params) => api.post('/api/generate-script-list', params)
export const saveScript = (params) => api.post('/api/save-script', params)

// ── Audio / Video ──
export const generateAudio = (params) => api.post('/api/generate-audio', params)
export const generateSrt = (params) => api.post('/api/generate-srt', params)
export const generateVideo = (params) => api.post('/api/generate-video', params)

// ── Async Tasks ──
export const asyncGenerateScriptList = (params) => api.post('/api/async/generate-script-list', params)
export const getTaskStatus = (taskId) => api.get(`/api/async/task/${taskId}`)

// ── Resources ──
export const getResources = (filePath) => api.get('/api/resources', { params: { file_path: filePath } })

// ── Restore ──
export const restoreJob = (jobId) => api.get('/api/restore-job', { params: { job_id: jobId } })

// ── History ──
export const getHistory = (params) => api.get('/api/history', { params })
export const getHistoryStats = () => api.get('/api/history/stats')
export const deleteHistory = (jobId) => api.delete(`/api/history/${jobId}`)

// ── Voices ──
export const getVoices = () => api.get('/api/voices')

export default api
