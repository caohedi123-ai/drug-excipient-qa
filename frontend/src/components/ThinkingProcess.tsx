import { type FC } from 'react'

interface Step {
  label: string
  status: 'pending' | 'active' | 'done' | 'error'
  detail?: string
}

interface ThinkingProcessProps {
  steps: Step[]
}

const statusConfig: Record<Step['status'], { icon: string; color: string }> = {
  pending: { icon: '○', color: 'text-[#484f58]' },
  active: { icon: '◌', color: 'text-[#58a6ff]' },
  done: { icon: '✓', color: 'text-[#3fb950]' },
  error: { icon: '✗', color: 'text-[#f85149]' },
}

export const ThinkingProcess: FC<ThinkingProcessProps> = ({ steps }) => {
  return (
    <details open className="ide-card">
        <summary className="px-3 py-2 text-xs font-medium text-[#8b949e] cursor-pointer hover:text-[#e6edf3] select-none">
        问题拆解与思考过程 ({steps.filter(s => s.status === 'done' || s.status === 'error').length}/{steps.length})
      </summary>
      <div className="px-3 pb-2 space-y-1.5">
        {steps.map((step, i) => {
          const cfg = statusConfig[step.status]
          return (
            <div key={i} className="flex items-start gap-2 text-xs">
              <span className={`flex-shrink-0 w-4 text-center ${cfg.color}`}>
                {step.status === 'active' ? (
                  <span className="inline-block animate-pulse">{cfg.icon}</span>
                ) : (
                  cfg.icon
                )}
              </span>
              <div className="flex-1 min-w-0">
                <span className={step.status === 'active' ? 'text-[#58a6ff]' : 'text-[#8b949e]'}>
                  {step.label}
                </span>
                {step.detail && (
                  <div className="text-[#484f58] mt-0.5 leading-relaxed">{step.detail}</div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </details>
  )
}
