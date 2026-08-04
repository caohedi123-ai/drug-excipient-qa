// 相对时间格式化：今天内显示"刚刚 / X分钟前 / X小时前"，隔天显示"X月X日"
export function formatRelativeTime(iso: string | undefined | null): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`
  const d = new Date(t)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return `${Math.floor(diff / 3_600_000)}小时前`
  // 隔天：显示日期
  return `${d.getMonth() + 1}月${d.getDate()}日`
}
