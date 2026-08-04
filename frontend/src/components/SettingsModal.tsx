import { useCallback, useEffect, useState } from 'react'
import { fetchSettings, updateSettings, type SettingsData } from '../lib/api'

interface Props {
  open: boolean
  onClose: () => void
}

const RETRIEVAL_FIELDS: Array<{ key: string; label: string; hint: string }> = [
  { key: 'max_retrieval_rounds', label: '最大检索轮数', hint: '每增加 1 轮约多 1 次检索+评估' },
  { key: 'retrieval_max_chars_per_source', label: '单源字符上限', hint: '每篇参考最多保留的字符数' },
  { key: 'retrieval_max_total_chars', label: '总字符预算', hint: '全部参考累计的字符上限' },
  { key: 'retrieval_max_store_chars', label: '入库截断字符', hint: '写入上下文的单源最大字符' },
  { key: 'history_inject_rounds', label: '历史注入轮数', hint: '追问时注入最近 N 轮对话' },
  { key: 'history_compress_rounds', label: '历史压缩轮数', hint: '超过该轮数触发摘要压缩' },
  { key: 'history_max_total_chars', label: '历史总字符预算', hint: '注入历史的最大总字符数' },
  { key: 'history_smart_truncate_chars', label: '智能截断字符', hint: '长回答单条截断阈值' },
]

const API_FIELDS: Array<{ key: 'deepseek_api_key' | 'tavily_api_key' | 'anysearch_api_key'; label: string; placeholder: string }> = [
  { key: 'deepseek_api_key', label: 'DeepSeek API Key', placeholder: 'sk-...' },
  { key: 'tavily_api_key', label: 'Tavily API Key', placeholder: 'tvly-...' },
  { key: 'anysearch_api_key', label: 'AnySearch API Key', placeholder: 'anys-...' },
]

export default function SettingsModal({ open, onClose }: Props) {
  const [data, setData] = useState<SettingsData | null>(null)
  const [apiInputs, setApiInputs] = useState<Record<string, string>>({})
  const [retrieval, setRetrieval] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await fetchSettings()
      setData(d)
      setRetrieval(Object.fromEntries(Object.entries(d.retrieval || {}).map(([k, v]) => [k, String(v)])))
      setApiInputs({})
    } catch (e: any) {
      setMsg({ ok: false, text: e?.message || '加载设置失败' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      setMsg(null)
      load()
    }
  }, [open, load])

  const handleSave = async () => {
    setSaving(true)
    setMsg(null)
    try {
      const payload: any = {}
      for (const f of API_FIELDS) {
        const v = apiInputs[f.key]?.trim()
        if (v) payload[f.key] = v
      }
      const retrievalPayload: Record<string, number> = {}
      for (const f of RETRIEVAL_FIELDS) {
        const v = Number(retrieval[f.key])
        if (Number.isFinite(v) && v > 0) retrievalPayload[f.key] = Math.floor(v)
      }
      if (Object.keys(retrievalPayload).length) payload.retrieval = retrievalPayload

      if (!Object.keys(payload).length) {
        setMsg({ ok: true, text: '没有需要保存的修改' })
        return
      }
      const d = await updateSettings(payload)
      setData(d)
      setRetrieval(Object.fromEntries(Object.entries(d.retrieval || {}).map(([k, v]) => [k, String(v)])))
      setApiInputs({})
      setMsg({ ok: true, text: '保存成功，立即生效' })
    } catch (e: any) {
      setMsg({ ok: false, text: e?.message || '保存失败' })
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-[#30363d] bg-[#161b22] shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#21262d] px-5 py-3">
          <h2 className="text-base font-semibold text-[#e6edf3]">系统设置</h2>
          <button
            className="rounded px-2 py-1 text-xl leading-none text-[#8b949e] hover:bg-[#21262d] hover:text-[#e6edf3]"
            onClick={onClose}
            aria-label="关闭"
          >
            ×
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
          {msg && (
            <div className={`rounded-md border px-3 py-2 text-sm ${msg.ok ? 'border-[#23863633] bg-[#1c2128] text-[#3fb950]' : 'border-[#f8514933] bg-[#1c2128] text-[#f85149]'}`}>
              {msg.text}
            </div>
          )}

          {/* API 密钥 */}
          <section>
            <h3 className="mb-2 text-sm font-semibold text-[#e6edf3]">API 密钥</h3>
            <p className="mb-3 text-xs text-[#8b949e]">留空表示沿用当前配置（默认值或已保存的值），不会明文显示已存密钥。</p>
            {loading ? (
              <p className="text-sm text-[#484f58]">加载中...</p>
            ) : (
              <div className="space-y-3">
                {API_FIELDS.map(f => {
                  const cur = data?.api_keys?.[f.key]
                  const placeholder = cur?.configured ? `已配置 ${cur.masked}` : `未配置，${f.placeholder}`
                  return (
                    <div key={f.key}>
                      <label className="mb-1 block text-xs font-medium text-[#c9d1d9]">{f.label}</label>
                      <input
                        type="password"
                        autoComplete="new-password"
                        placeholder={placeholder}
                        value={apiInputs[f.key] || ''}
                        onChange={e => setApiInputs(prev => ({ ...prev, [f.key]: e.target.value }))}
                        className="w-full rounded-md border border-[#30363d] bg-[#0d1117] px-3 py-1.5 text-sm text-[#e6edf3] placeholder-[#484f58] outline-none focus:border-[#58a6ff] focus:ring-1 focus:ring-[#58a6ff33]"
                      />
                    </div>
                  )
                })}
              </div>
            )}
          </section>

          {/* 检索自定义配置（对应"自定义"档位） */}
          <section>
            <h3 className="mb-2 text-sm font-semibold text-[#e6edf3]">检索自定义配置</h3>
            <p className="mb-3 text-xs text-[#8b949e]">此配置对应对话框旁的"自定义"档位。档位选择预设值不受影响。</p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {RETRIEVAL_FIELDS.map(f => (
                <div key={f.key}>
                  <label className="mb-1 block text-xs font-medium text-[#c9d1d9]" title={f.hint}>
                    {f.label}
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={retrieval[f.key] ?? ''}
                    onChange={e => setRetrieval(prev => ({ ...prev, [f.key]: e.target.value }))}
                    className="w-full rounded-md border border-[#30363d] bg-[#0d1117] px-3 py-1.5 text-sm text-[#e6edf3] outline-none focus:border-[#58a6ff] focus:ring-1 focus:ring-[#58a6ff33]"
                  />
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-[#21262d] px-5 py-3">
          <button
            className="rounded-md border border-[#30363d] px-4 py-1.5 text-sm text-[#c9d1d9] hover:bg-[#21262d]"
            onClick={onClose}
            disabled={saving}
          >
            取消
          </button>
          <button
            className="rounded-md bg-[#1f6feb] px-4 py-1.5 text-sm font-medium text-white hover:bg-[#388bfd] disabled:opacity-50"
            onClick={handleSave}
            disabled={saving || loading}
          >
            {saving ? '保存中...' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
