import { useState, useCallback, useRef, useEffect } from 'react'
import { Sidebar } from './components/Sidebar'
import { ChatContainer } from './components/ChatContainer'
import { ExcipientLookup } from './components/ExcipientLookup'
import LoginPage from './components/LoginPage'
import { AuthProvider, useAuth } from './lib/AuthContext'
import { fetchLookupHistory, fetchConversations } from './lib/api'
import type { Conversation, LookupHistoryItem } from './types'
import type { ExcipientLookupResult } from './lib/api'

type PageMode = 'chat' | 'lookup'

function AppContent() {
  const { isLoggedIn, loading: authLoading } = useAuth()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [mode, setMode] = useState<PageMode>('chat')
  const [lookupHistory, setLookupHistory] = useState<LookupHistoryItem[]>([])
  const [lookupRefreshKey, setLookupRefreshKey] = useState(0)
  const [preloadedLookup, setPreloadedLookup] = useState<LookupHistoryItem | null>(null)
  const activeConvRef = useRef<Conversation | undefined>(undefined)
  const [convsLoadedFromBackend, setConvsLoadedFromBackend] = useState(false)

  const activeConversation = conversations.find(c => c.id === activeId)

  // 加载速查历史
  const loadHistory = useCallback(async () => {
    try {
      const history = await fetchLookupHistory()
      setLookupHistory(history)
    } catch {
      // 静默失败
    }
  }, [])

  // 从后端加载已有 AI 问答会话列表
  useEffect(() => {
    if (!isLoggedIn || convsLoadedFromBackend) return
    fetchConversations()
      .then(data => {
        if (data && data.length > 0) {
          setConversations(data.map(c => ({
            id: c.id,
            title: c.title || '未命名会话',
            thread_id: c.thread_id,
            created_at: c.created_at || '',
            updated_at: c.updated_at || '',
          })))
        }
        setConvsLoadedFromBackend(true)
      })
      .catch(err => {
        console.warn('加载历史会话失败:', err)
        setConvsLoadedFromBackend(true)
      })
  }, [isLoggedIn, convsLoadedFromBackend])

  useEffect(() => {
    if (isLoggedIn) {
      loadHistory()
    }
  }, [isLoggedIn, loadHistory, lookupRefreshKey])

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

  const handleLookupSuccess = useCallback((_result: ExcipientLookupResult) => {
    setLookupRefreshKey(k => k + 1)
  }, [])

  const handleSelectLookupHistory = useCallback((id: string) => {
    const item = lookupHistory.find(h => h.id === id)
    if (item) {
      setPreloadedLookup(item)
      setMode('lookup')
    }
  }, [lookupHistory])

  // 认证加载中
  if (authLoading) {
    return (
      <div style={{
        width: '100vw', height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: '#0d1117', color: '#8b949e', fontSize: 14,
      }}>
        <svg width="20" height="20" viewBox="0 0 16 16" fill="none" style={{ animation: 'spin 1s linear infinite', marginRight: 10 }}>
          <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" strokeDasharray="28" strokeLinecap="round"/>
        </svg>
        加载中...
      </div>
    )
  }

  // 未登录 → 登录页
  if (!isLoggedIn) {
    return <LoginPage />
  }

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
        lookupHistory={lookupHistory}
        onSelectLookup={handleSelectLookupHistory}
      />
      <div className="flex-1 flex flex-col min-w-0 min-h-0 overflow-hidden">
        <div className="flex items-center gap-0 px-4 h-10 border-b border-[#21262d] bg-[#0d1117]">
          <button
            onClick={handleToggleSidebar}
            className="p-1 rounded-md text-[#8b949e] hover:text-[#e6edf3] hover:bg-[#1c2128] transition-colors duration-100 mr-2"
            title="切换侧边栏"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="flex items-center h-full gap-0 -mb-px">
            <button
              onClick={() => setMode('chat')}
              className={`flex items-center gap-1.5 px-3 h-full text-sm font-medium border-b-2 transition-colors duration-100 ${
                mode === 'chat'
                  ? 'text-[#e6edf3] border-[#58a6ff]'
                  : 'text-[#8b949e] border-transparent hover:text-[#e6edf3] hover:border-[#30363d]'
              }`}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
              </svg>
              AI 问答
            </button>
            <button
              onClick={() => setMode('lookup')}
              className={`flex items-center gap-1.5 px-3 h-full text-sm font-medium border-b-2 transition-colors duration-100 ${
                mode === 'lookup'
                  ? 'text-[#d29922] border-[#d29922]'
                  : 'text-[#8b949e] border-transparent hover:text-[#e6edf3] hover:border-[#30363d]'
              }`}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              速查
            </button>
          </div>
        </div>
        <div className={mode === 'chat' ? 'flex-1 flex flex-col min-w-0 min-h-0' : 'hidden'}>
          <ChatContainer
            conversation={activeConversation}
            onUpdate={handleUpdateConversation}
          />
        </div>
        <div className={mode === 'lookup' ? 'flex-1 flex flex-col min-w-0 min-h-0' : 'hidden'}>
          <ExcipientLookup
            onLookupSuccess={handleLookupSuccess}
            preloadedResult={preloadedLookup}
            onConsumed={() => setPreloadedLookup(null)}
          />
        </div>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
