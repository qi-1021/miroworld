import service from './index'

export const getModelRegistry = () => service.get('/api/models/registry')

export const getEmbeddingPreference = () => service.get('/api/models/embedding-preference')

export const setEmbeddingPreference = (preference) => (
  service.put('/api/models/embedding-preference', { preference })
)

export const detectModelConnection = (draft) => (
  service.post('/api/models/connections/detect', draft)
)

export const createModelConnection = (draft) => (
  service.post('/api/models/connections', draft)
)

export const updateModelConnection = (connectionId, draft) => (
  service.patch(`/api/models/connections/${connectionId}`, draft)
)

export const deleteModelConnection = (connectionId, revision) => (
  service.delete(`/api/models/connections/${connectionId}`, { params: { revision } })
)

export const discoverConnectionModels = (connectionId) => (
  service.post(`/api/models/connections/${connectionId}/discover`)
)

export const createModelEntry = (entry) => (
  service.post('/api/models/entries', entry)
)

export const deleteModelEntry = (entryId, revision) => (
  service.delete(`/api/models/entries/${entryId}`, { params: { revision } })
)

export const getProjectModelBindings = (projectId) => (
  service.get(`/api/models/projects/${projectId}/bindings`)
)

export const updateProjectModelBindings = (projectId, payload) => (
  service.put(`/api/models/projects/${projectId}/bindings`, payload)
)

// ==================== 本地向量模型 ====================

export const scanLocalModels = () => service.get('/api/models/local/scan')

export const inspectLocalModel = (name) => (
  service.get(`/api/models/local/${encodeURIComponent(name)}/inspect`)
)

export const testLocalModel = (name) => (
  service.post(`/api/models/local/${encodeURIComponent(name)}/test`)
)

export const registerLocalModel = (name, payload = {}) => (
  service.post(`/api/models/local/${encodeURIComponent(name)}/register`, payload)
)
