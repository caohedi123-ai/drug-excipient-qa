import { type FC, useState, useRef, useCallback, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { lookupExcipient } from '../lib/api'
import type { ExcipientLookupEntity, LookupModule } from '../lib/api'
import type { LookupHistoryItem } from '../types'

// ── Entity 卡片（产品基本信息的所有结构化字段）──
const EntityCard: FC<{ entity: ExcipientLookupEntity; basicFields: Array<{key:string;label:string;value:string;source:string;sourceUrl:string;confidence:number}> }> = ({ entity, basicFields }) => {
  // 构建字段行
  const rows: Array<{ label: string; value: string; source?: string }> = []

  for (const f of basicFields) {
    rows.push({ label: f.label, value: f.value, source: `来源: ${f.source} | 置信度: ${f.confidence}%` })
  }

  if (rows.length === 0) return null

  // 分组显示：前6个字段为第1组，其余折叠
  const [expanded, setExpanded] = useState(false)
  const primaryRows = rows.slice(0, 8)
  const extraRows = rows.slice(8)
  const hasMore = extraRows.length > 0

  return (
    <div className="bg-[#161b22] border border-[#21262d] rounded-md p-3">
      <h3 className="text-xs font-semibold text-[#8b949e] uppercase tracking-wider mb-2">基本信息</h3>
      <div className={`grid gap-x-4 gap-y-1 text-sm ${primaryRows.length > 4 ? 'grid-cols-2' : 'grid-cols-1'}`}>
        {[...primaryRows, ...(expanded ? extraRows : [])].map((r, i) => (
          <div key={i} className="flex items-baseline gap-1.5 py-0.5 border-b border-[#21262d] last:border-0">
            <span className="text-[#8b949e] text-xs flex-shrink-0 min-w-[4rem]">{r.label}</span>
            <span className="text-[#e6edf3] font-mono text-xs break-all">{r.value || '—'}</span>
            {r.source && (
              <span className="text-[10px] text-[#484f58] ml-auto flex-shrink-0 hidden lg:inline">{r.source}</span>
            )}
          </div>
        ))}
      </div>
      {hasMore && (
        <button onClick={() => setExpanded(!expanded)} className="mt-2 text-xs text-[#58a6ff] hover:text-[#79c0ff] transition-colors">
          {expanded ? '收起' : `展开全部 (${primaryRows.length + extraRows.length} 项)`}
        </button>
      )}
    </div>
  )
}

// ── 模块卡片（Markdown 格式化 + 中英翻译切换）──
const ModuleCard: FC<{ moduleName: string; moduleData: LookupModule }> = ({ moduleName, moduleData }) => {
  const { fields, text_parts, text_parts_cn } = moduleData
  const [showCN, setShowCN] = useState(false)
  const hasCN = text_parts_cn && text_parts_cn.length > 0

  return (
    <div className="bg-[#161b22] border border-[#21262d] rounded-md p-3">
      <h3 className="text-xs font-semibold text-[#d29922] uppercase tracking-wider mb-2 flex items-center gap-1.5">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12" />
        </svg>
        {moduleName}
      </h3>

      {/* 字段表 */}
      {fields.length > 0 && (
        <div className="overflow-x-auto mb-2">
          <table className="w-full text-xs">
            <tbody>
              {fields.map((f, i) => (
                <tr key={i} className="border-b border-[#21262d] last:border-0">
                  <td className="py-1.5 pr-3 text-[#8b949e] whitespace-nowrap">{f.label}</td>
                  <td className="py-1.5 pr-3 text-[#e6edf3] break-all">{f.value || '—'}</td>
                  <td className="py-1.5 text-[#484f58] whitespace-nowrap text-right text-[10px]">
                    {f.source} {f.confidence}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 文本详情 */}
      {text_parts.length > 0 && (
        <div>
          <div className="markdown-body text-xs leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {text_parts.join('\n\n')}
            </ReactMarkdown>
          </div>
          {/* 中文翻译切换 */}
          {hasCN && (
            <>
              <button
                onClick={() => setShowCN(!showCN)}
                className="mt-2 text-[11px] text-[#58a6ff] hover:text-[#79c0ff] flex items-center gap-1 transition-colors"
              >
                <svg className={`w-3 h-3 transition-transform ${showCN ? 'rotate-90' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
                {showCN ? '隐藏中文翻译' : '显示中文翻译'}
              </button>
              {showCN && (
                <div className="mt-2 pt-2 border-t border-[#21262d] markdown-body text-xs leading-relaxed">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {text_parts_cn.join('\n\n')}
                  </ReactMarkdown>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}


export const ExcipientLookup: FC<{
  onLookupSuccess?: (result: any) => void
  preloadedResult?: LookupHistoryItem | null
  onConsumed?: () => void
}> = ({ onLookupSuccess, preloadedResult, onConsumed }) => {
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [entity, setEntity] = useState<ExcipientLookupEntity | null>(null)
  const [modules, setModules] = useState<Record<string, LookupModule>>({})
  const [citations, setCitations] = useState<Array<{ source_name: string; source_url: string; snippet: string }>>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [searched, setSearched] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleLookup = useCallback(async () => {
    const q = name.trim()
    if (!q) return
    setLoading(true)
    setError(null)
    setContent('')
    setEntity(null)
    setModules({})
    setCitations([])
    setSearched(true)
    try {
      const res = await lookupExcipient(q)
      if (!res.ok) {
        setError(res.content || '速查返回异常')
        return
      }
      setContent(res.content || '')
      setEntity(res.entity)
      setModules(res.modules || {})
      setCitations(res.citations || [])
      onLookupSuccess?.(res)
    } catch (e: any) {
      if (e?.message === 'AUTH_REQUIRED') {
        setError('请先登录')
        return
      }
      setError(e?.message || '速查请求失败，请确认后端服务已启动')
    } finally {
      setLoading(false)
    }
  }, [name])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !loading && name.trim()) handleLookup()
    },
    [handleLookup, loading, name],
  )

  // 消费预加载的历史结果
  useEffect(() => {
    if (!preloadedResult) return
    setName(preloadedResult.name)
    setEntity(preloadedResult.entity)
    setModules((preloadedResult.modules || {}) as Record<string, LookupModule>)
    setCitations((preloadedResult.citations || []) as Array<{ source_name: string; source_url: string; snippet: string }>)
    setContent('')
    setError(null)
    setSearched(true)
    setLoading(false)
    onConsumed?.()
  }, [preloadedResult?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  // 提取'产品基本信息'模块的字段用于实体卡片
  const basicFieldKeys = new Set([
    'drug_name_cn','drug_name_en','excipient_name_cn','excipient_name_en',
    'brand_name','cas_number','molecular_formula','molecular_weight',
    'structure_id','iupac_name','logp','unii_code','product_type',
    'chembl_id',
  ])
  const basicFields = (modules['产品基本信息']?.fields || []).filter(f =>
    basicFieldKeys.has(f.key)
  )
  // 其余模块
  const otherModules = Object.entries(modules).filter(([k]) => k !== '产品基本信息')

  return (
    <div className="flex-1 flex flex-col h-full min-w-0">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 h-10 border-b border-[#21262d] bg-[#0d1117]">
        <svg className="w-4 h-4 text-[#d29922] flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <span className="text-sm font-medium text-[#e6edf3]">原辅料基本信息速查</span>
        <span className="text-[10px] text-[#d29922] uppercase tracking-wider border border-[#d2992233] rounded px-1.5">速查</span>
      </div>

      {/* Input area */}
      <div className="border-b border-[#21262d] px-4 py-3 bg-[#0d1117]">
        <div className="max-w-3xl mx-auto flex gap-2">
          <div className="flex-1 relative">
            <input
              ref={inputRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入原辅料名称（中文名/英文名/商品名/CAS均可）"
              disabled={loading}
              className="ide-input h-9 pr-9"
              autoFocus
            />
            {name.length > 0 && (
              <button
                onClick={() => { setName(''); inputRef.current?.focus() }}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded text-[#484f58] hover:text-[#8b949e] transition-colors"
                title="清空"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
          <button
            onClick={handleLookup}
            disabled={loading || !name.trim()}
            className="btn-primary h-9"
          >
            {loading ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                查询中
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                速查
              </>
            )}
          </button>
        </div>
      </div>

      {/* Result area */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="max-w-3xl mx-auto">
          {/* Idle state */}
          {!searched && !loading && (
            <div className="flex items-center justify-center h-full min-h-[300px]">
              <div className="text-center max-w-md">
                <div className="w-12 h-12 mx-auto mb-4 rounded-lg bg-[#d299221a] border border-[#d2992233] flex items-center justify-center">
                  <svg className="w-6 h-6 text-[#d29922]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m5.231 13.481L15 17.25m-4.5-15H5.625c-.621 0-1.125.504-1.125 1.125v16.5c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9zm3.75 11.625a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
                  </svg>
                </div>
                <h2 className="text-base font-semibold text-[#e6edf3] mb-1">原辅料基本信息速查</h2>
                <p className="text-xs text-[#8b949e]">
                  输入原辅料名称，快速获取基本信息、分子式、CAS、UNII、结构式、注册状态、专利等，无需复杂对话。
                </p>
                <div className="mt-4 grid grid-cols-2 gap-2 text-left">
                  {['乳糖', '微晶纤维素', '阿可替尼', '阿司匹林'].map((example) => (
                    <button
                      key={example}
                      onClick={() => { setName(example); setSearched(false); setContent(''); setEntity(null); setModules({}); setCitations([]); setError(null); inputRef.current?.focus() }}
                      className="text-xs text-[#58a6ff] hover:text-[#79c0ff] bg-[#1f6feb1a] hover:bg-[#1f6feb33] border border-[#1f6feb33] rounded px-2 py-1.5 transition-colors text-left"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Loading skeleton */}
          {loading && (
            <div className="space-y-4 animate-pulse">
              <div className="h-4 bg-[#21262d] rounded w-1/3" />
              <div className="space-y-2">
                <div className="h-3 bg-[#21262d] rounded" />
                <div className="h-3 bg-[#21262d] rounded w-4/5" />
                <div className="h-3 bg-[#21262d] rounded w-2/3" />
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="bg-[#f851491a] border border-[#f8514933] rounded-md px-4 py-3">
              <div className="flex items-start gap-2">
                <svg className="w-4 h-4 text-[#f85149] mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                </svg>
                <div>
                  <p className="text-sm font-medium text-[#f85149]">速查出错</p>
                  <p className="text-xs text-[#f85149] opacity-80 mt-0.5">{error}</p>
                </div>
              </div>
            </div>
          )}

          {/* Result content */}
          {!loading && Object.keys(modules).length > 0 && (
            <div className="space-y-4">
              {/* 1) 基本信息卡片 */}
              <EntityCard entity={entity!} basicFields={basicFields} />

              {/* 2) 其他模块卡片 */}
              {otherModules.map(([modName, modData]) => (
                <ModuleCard key={modName} moduleName={modName} moduleData={modData} />
              ))}

              {/* 3) Citations */}
              {citations.length > 0 && (
                <details className="reference-details group" open>
                  <summary className="text-xs font-medium text-[#8b949e] flex items-center gap-1.5 cursor-pointer hover:text-[#e6edf3] select-none py-0.5">
                    <svg className="w-3 h-3 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                    </svg>
                    数据来源 ({citations.length})
                  </summary>
                  <div className="mt-1 space-y-1">
                    {citations.map((c, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs text-[#8b949e] p-1.5 rounded hover:bg-[#1c2128] transition-colors">
                        <span className="text-[#d29922] font-mono font-bold text-[10px] mt-0.5">[{i + 1}]</span>
                        <div className="min-w-0">
                          {c.source_url ? (
                            <a
                              href={c.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[#58a6ff] hover:text-[#79c0ff] underline break-all"
                            >
                              {c.source_name || c.source_url}
                            </a>
                          ) : (
                            <span className="text-[#e6edf3]">{c.source_name || '未知来源'}</span>
                          )}
                          {c.snippet && (
                            <p className="text-[#484f58] mt-0.5 line-clamp-2">{c.snippet}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </details>
              )}

              {/* Retry hint */}
              <div className="text-center pb-4">
                <span className="text-xs text-[#484f58]">
                  如需了解更详细的药理信息或进行对话式问答，请切换到「AI 问答」。
                </span>
              </div>
            </div>
          )}

          {/* 向后兼容：无 modules 但有 content 时展示文本 */}
          {!loading && Object.keys(modules).length === 0 && content && (
            <div className="space-y-4">
              <EntityCard entity={entity!} basicFields={basicFields} />
              <div className="bubble-assistant max-w-none">
                <div className="text-sm break-words text-[#e6edf3] markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
