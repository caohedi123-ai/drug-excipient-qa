import { type FC, useRef, useState } from 'react'
import type { Conversation, LookupHistoryItem } from '../types'
import { formatRelativeTime } from '../lib/time'

interface SidebarProps {
  conversations: Conversation[]
  activeId: string | null
  open: boolean
  onNew: () => void
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onRename: (id: string, title: string) => void
  onClose: () => void
  lookupHistory: LookupHistoryItem[]
  onSelectLookup: (id: string) => void
  onRenameLookup: (id: string, title: string) => void
}

export const Sidebar: FC<SidebarProps> = ({
  conversations,
  activeId,
  open,
  onNew,
  onSelect,
  onDelete,
  onRename,
  onClose,
  lookupHistory,
  onSelectLookup,
  onRenameLookup,
}) => {
  const [editing, setEditing] = useState<{ kind: 'conv' | 'lookup'; id: string } | null>(null)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const startRename = (kind: 'conv' | 'lookup', id: string, currentTitle: string) => {
    setEditing({ kind, id })
    setDraft(currentTitle)
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  const commitRename = () => {
    if (!editing) return
    const title = draft.trim()
    if (title) {
      if (editing.kind === 'conv') onRename(editing.id, title)
      else onRenameLookup(editing.id, title)
    }
    setEditing(null)
  }

  if (!open) return null

  return (
    <div className="w-60 h-full flex flex-col bg-[#161b22] border-r border-[#21262d] flex-shrink-0">
      {/* Brand header with logo */}
      <div className="flex items-center gap-2 px-3 h-12 border-b border-[#21262d] flex-shrink-0">
        <img
          src="/zhongnuo-logo.jpg"
          alt="中诺"
          className="h-7 w-7 rounded object-cover flex-shrink-0"
        />
        <span className="text-[13px] font-semibold text-[#e6edf3] truncate">中诺药物原辅料问答</span>
      </div>

      {/* Header */}
      <div className="panel-header">
        <svg className="w-3.5 h-3.5 text-[#58a6ff]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-3-3v6m-7 4h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
        <span>历史记录</span>
      </div>

      {/* New Conversation button */}
      <div className="px-3 py-2">
        <button onClick={onNew} className="btn-primary w-full">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          新建问答
        </button>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
        {conversations.length === 0 && lookupHistory.length === 0 && (
          <div className="text-xs text-[#484f58] text-center py-8">
            暂无记录
          </div>
        )}
        {conversations.map(conv => {
          const isActive = conv.id === activeId
          const isEditing = editing?.kind === 'conv' && editing.id === conv.id
          return (
            <div
              key={conv.id}
              onClick={() => { if (!isEditing) onSelect(conv.id) }}
              className={`
                group flex items-center gap-2 px-3 py-1.5 rounded-md cursor-pointer text-sm
                transition-colors duration-100
                ${isActive ? 'bg-[#1f6feb33] text-[#e6edf3]' : 'text-[#8b949e] hover:bg-[#1c2128] hover:text-[#e6edf3]'}
              `}
            >
              {isEditing ? (
                <input
                  ref={inputRef}
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') commitRename()
                    if (e.key === 'Escape') setEditing(null)
                  }}
                  onBlur={commitRename}
                  onClick={e => e.stopPropagation()}
                  className="flex-1 min-w-0 text-sm bg-[#0d1117] border border-[#30363d] rounded px-1.5 py-0.5 text-[#e6edf3] outline-none focus:border-[#58a6ff]"
                  maxLength={80}
                />
              ) : (
                <>
                  <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                  <span className="flex-1 truncate">{conv.title}</span>
                  <button
                    onClick={e => { e.stopPropagation(); startRename('conv', conv.id, conv.title) }}
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[#21262d] text-[#484f58] hover:text-[#58a6ff] transition-all duration-100"
                    title="重命名"
                  >
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                  </button>
                  <button
                    onClick={e => { e.stopPropagation(); onDelete(conv.id) }}
                    className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[#21262d] text-[#484f58] hover:text-[#f85149] transition-all duration-100"
                    title="删除"
                  >
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </>
              )}
            </div>
          )
        })}

        {/* 速查历史分组 */}
        {lookupHistory.length > 0 && (
          <>
            <div className="pt-3 pb-1 px-1">
              <div className="text-[10px] font-semibold text-[#d29922] uppercase tracking-wider px-2 py-1">
                速查历史
              </div>
            </div>
            {lookupHistory.map(item => {
              const isEditing = editing?.kind === 'lookup' && editing.id === item.id
              return (
                <div
                  key={item.id}
                  onClick={() => { if (!isEditing) onSelectLookup(item.id) }}
                  className="group flex items-center gap-2 px-3 py-1.5 rounded-md text-sm text-[#8b949e] hover:bg-[#1c2128] hover:text-[#e6edf3] cursor-pointer transition-colors duration-100"
                >
                  {isEditing ? (
                    <input
                      ref={inputRef}
                      value={draft}
                      onChange={e => setDraft(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === 'Enter') commitRename()
                        if (e.key === 'Escape') setEditing(null)
                      }}
                      onBlur={commitRename}
                      onClick={e => e.stopPropagation()}
                      className="flex-1 min-w-0 text-xs bg-[#0d1117] border border-[#30363d] rounded px-1.5 py-0.5 text-[#e6edf3] outline-none focus:border-[#58a6ff]"
                      maxLength={80}
                    />
                  ) : (
                    <>
                      <svg className="w-3.5 h-3.5 flex-shrink-0 text-[#d29922]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                      </svg>
                      <span className="flex-1 truncate text-xs">{item.name}</span>
                      <span className="text-[10px] text-[#484f58]">
                        {formatRelativeTime(item.created_at)}
                      </span>
                      <button
                        onClick={e => { e.stopPropagation(); startRename('lookup', item.id, item.name) }}
                        className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[#21262d] text-[#484f58] hover:text-[#58a6ff] transition-all duration-100"
                        title="重命名"
                      >
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>
                    </>
                  )}
                </div>
              )
            })}
          </>
        )}
      </div>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-[#21262d]">
        <div className="text-[10px] text-[#484f58]">中诺药物原辅料知识问答助手</div>
      </div>
    </div>
  )
}
