import { useState, useCallback, useRef } from 'react'
import { Sidebar } from './components/Sidebar'
import { ChatContainer } from './components/ChatContainer'
import type { Conversation } from './types'

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const activeConvRef = useRef<Conversation | undefined>(undefined)

  const activeConversation = conversations.find(c => c.id === activeId)

  const handleNewConversation = useCallback(() => {
    const id = crypto.randomUUID()
    const now = new Date().toISOString()
    const conv: Conversation = {
      id,
      title: '新问答',
      thread_id: crypto.randomUUID(),
      created_at: now,
      updated_at: now,
    }
    setConversations(prev => [conv, ...prev])
    setActiveId(id)
  }, [])

  const handleSelectConversation = useCallback((id: string) => {
    setActiveId(id)
  }, [])

  const handleUpdateConversation = useCallback((conv: Conversation) => {
    setConversations(prev => {
      const exists = prev.some(c => c.id === conv.id)
      if (exists) {
        return prev.map(c => c.id === conv.id ? { ...conv, updated_at: new Date().toISOString() } : c)
      }
      // 新增的对话（如首次发送消息自动创建的），加到列表最前面
      return [{ ...conv, updated_at: new Date().toISOString() }, ...prev]
    })
    activeConvRef.current = conv
  }, [])

  const handleDeleteConversation = useCallback((id: string) => {
    setConversations(prev => prev.filter(c => c.id !== id))
    if (activeId === id) setActiveId(null)
  }, [activeId])

  const handleToggleSidebar = useCallback(() => {
    setSidebarOpen(prev => !prev)
  }, [])

  return (
    <div className="h-full w-full flex overflow-hidden bg-[#0d1117]">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        open={sidebarOpen}
        onNew={handleNewConversation}
        onSelect={handleSelectConversation}
        onDelete={handleDeleteConversation}
        onClose={() => setSidebarOpen(false)}
      />
      <ChatContainer
        key={activeId || 'empty'}
        conversation={activeConversation}
        onUpdate={handleUpdateConversation}
        onToggleSidebar={handleToggleSidebar}
      />
    </div>
  )
}
