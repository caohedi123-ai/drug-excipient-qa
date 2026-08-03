// 兼容非安全上下文（HTTP 公网 IP 部署）：
// crypto.randomUUID() 仅在 HTTPS 或 localhost 环境可用，
// 此处提供 RFC4122 v4 降级实现，保证任何浏览器环境都能生成 UUID。
export function uuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}
