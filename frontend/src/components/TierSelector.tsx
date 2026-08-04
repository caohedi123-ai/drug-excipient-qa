import { useEffect, useRef, useState } from 'react'

export type TierId = 'flash' | 'fast' | 'balanced' | 'quality' | 'pro' | 'custom'

export const TIER_ORDER: TierId[] = ['flash', 'fast', 'balanced', 'quality', 'pro', 'custom']
export const TIER_LABELS: Record<TierId, string> = {
  flash: 'Flash 极速',
  fast: 'Fast 快速',
  balanced: 'Balanced 均衡',
  quality: 'Quality 高质量',
  pro: 'Pro 深度',
  custom: '自定义',
}
export const DEFAULT_TIER: TierId = 'pro'

const STORAGE_KEY = 'pharma_tier'

export function loadSavedTier(): TierId {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v && (TIER_ORDER as string[]).includes(v)) return v as TierId
  } catch { /* ignore */ }
  return DEFAULT_TIER
}

function saveTier(tier: TierId) {
  try {
    localStorage.setItem(STORAGE_KEY, tier)
  } catch { /* ignore */ }
}

interface Props {
  value: TierId
  onChange: (tier: TierId) => void
}

export default function TierSelector({ value, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const pick = (tier: TierId) => {
    onChange(tier)
    saveTier(tier)
    setOpen(false)
  }

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 rounded-md border border-[#30363d] bg-[#161b22] px-2 py-1 text-xs text-[#c9d1d9] hover:border-[#58a6ff] hover:text-[#e6edf3]"
        title="检索档位：Flash 速度优先 → Pro 质量优先（最长时间）"
      >
        <span className="font-medium">{TIER_LABELS[value]}</span>
        <svg className="h-3 w-3 opacity-60" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {open && (
        <div className="absolute bottom-full left-0 z-40 mb-1 w-48 overflow-hidden rounded-lg border border-[#30363d] bg-[#161b22] py-1 shadow-xl">
          <div className="border-b border-[#21262d] px-3 py-1.5 text-[11px] text-[#8b949e]">
            Flash 速度优先 → Pro 质量优先
          </div>
          {TIER_ORDER.map(tier => (
            <button
              key={tier}
              type="button"
              onClick={() => pick(tier)}
              className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-[#1c2128] ${
                tier === value ? 'font-medium text-[#58a6ff]' : 'text-[#c9d1d9]'
              }`}
            >
              <span>{TIER_LABELS[tier]}</span>
              {tier === value && <span className="text-[#58a6ff]">✓</span>}
            </button>
          ))}
          {value === 'custom' && (
            <div className="border-t border-[#21262d] px-3 py-1.5 text-[11px] text-[#8b949e]">
              在「系统设置 → 检索自定义配置」中修改
            </div>
          )}
        </div>
      )}
    </div>
  )
}
