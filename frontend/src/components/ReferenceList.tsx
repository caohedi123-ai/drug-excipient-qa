import { type FC, useState } from 'react'

interface RefItem {
  source: string
  sourceName: string
  title: string
  subtitle?: string
  score?: number
  url?: string
  snippet?: string
}

interface ReferenceListProps {
  references: RefItem[]
}

const SOURCE_ICONS: Record<string, { icon: string; label: string; color: string }> = {
  pubchem: { icon: '⚗', label: 'PubChem', color: '#3fb950' },
  drugbank: { icon: '💊', label: 'DrugBank', color: '#58a6ff' },
  fda_iig: { icon: '🏛', label: 'FDA IIG', color: '#f78166' },
  fda_unii: { icon: '🔬', label: 'FDA UNII', color: '#d2a8ff' },
  dailymed: { icon: '📋', label: 'DailyMed', color: '#79c0ff' },
  wikipedia: { icon: '📖', label: 'Wikipedia', color: '#a5d6ff' },
  pubmed: { icon: '📚', label: 'PubMed', color: '#ffa657' },
  drugcentral: { icon: '🧬', label: 'DrugCentral', color: '#7ee787' },
  anysearch: { icon: '🌐', label: 'Web', color: '#8b949e' },
  web: { icon: '🌐', label: 'Web', color: '#8b949e' },
}

/** 按 sourceName 分组 */
function groupBySourceName(refs: RefItem[]): Map<string, RefItem[]> {
  const groups = new Map<string, RefItem[]>()
  for (const r of refs) {
    const key = r.sourceName || r.source || 'Unknown'
    const existing = groups.get(key)
    if (existing) {
      existing.push(r)
    } else {
      groups.set(key, [r])
    }
  }
  return groups
}

export const ReferenceList: FC<ReferenceListProps> = ({ references }) => {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => {
    // 默认展开所有有 URL 的来源组
    const initial = new Set<string>()
    const groups = groupBySourceName(references)
    for (const [key, refs] of groups) {
      // 有可点击链接的组默认展开
      if (refs.some(r => r.url)) {
        initial.add(key)
      }
    }
    // 最多展开 3 组
    return new Set([...initial].slice(0, 3))
  })

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }

  if (references.length === 0) return null

  const groups = groupBySourceName(references)

  return (
    <div className="mt-3 space-y-1.5">
      <div className="text-xs font-medium text-[#8b949e] mb-2">
        参考来源 ({references.length})
      </div>
      {[...groups.entries()].map(([sourceName, refs]) => {
        const sourceKey = refs[0]?.source || 'web'
        const sourceInfo = SOURCE_ICONS[sourceKey] || SOURCE_ICONS.web
        const isExpanded = expandedGroups.has(sourceName)

        return (
          <div key={sourceName} className="rounded-md border border-[#21262d] overflow-hidden">
            {/* Group Header */}
            <button
              onClick={() => toggleGroup(sourceName)}
              className="w-full flex items-center gap-2 px-3 py-2 text-xs bg-[#161b22]
                         hover:bg-[#1c2128] transition-colors text-left"
            >
              <svg
                className={`w-3 h-3 transition-transform flex-shrink-0 ${
                  isExpanded ? 'rotate-90' : ''
                }`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
              <span className="text-sm">{sourceInfo.icon}</span>
              <span
                className="font-medium truncate"
                style={{ color: sourceInfo.color }}
              >
                {sourceInfo.label}
              </span>
              <span className="text-[#484f58]">{sourceName}</span>
              <span className="ml-auto text-[#484f58]">{refs.length} 条</span>
            </button>

            {/* Items */}
            {isExpanded && (
              <div className="divide-y divide-[#21262d]">
                {refs.map((ref, idx) => (
                  <div key={idx} className="px-3 py-2 hover:bg-[#161b22]/50 transition-colors">
                    <div className="text-xs text-[#e6edf3] leading-relaxed mb-1">
                      {ref.title}
                    </div>
                    {ref.snippet && (
                      <div className="text-[11px] text-[#8b949e] leading-relaxed line-clamp-2 mb-1.5">
                        {ref.snippet}
                      </div>
                    )}
                    {ref.url ? (
                      <a
                        href={ref.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-[11px] text-[#58a6ff]
                                   hover:text-[#79c0ff] hover:underline transition-colors"
                      >
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                          <polyline points="15 3 21 3 21 9" />
                          <line x1="10" y1="14" x2="21" y2="3" />
                        </svg>
                        查看原文
                      </a>
                    ) : (
                      <span className="text-[11px] text-[#484f58] italic">无原始链接</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
