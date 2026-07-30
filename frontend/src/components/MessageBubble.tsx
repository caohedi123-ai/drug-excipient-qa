import { type FC, useState, useCallback, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeRaw from 'rehype-raw'
import remarkGfm from 'remark-gfm'
import type { Message } from '../types'

interface MessageBubbleProps {
  message: Message
}

export const MessageBubble: FC<MessageBubbleProps> = ({ message }) => {
  const isUser = message.role === 'user'
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = message.content
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }, [message.content])

  // 预处理：将 [N] 引用角标替换为带样式的 HTML sup 标签
  // 正则：只匹配独立的 [数字] 模式，不匹配 Markdown 链接 [text](url) 中的括号
  const processedContent = useMemo(() => {
    if (isUser) return message.content
    return message.content.replace(
      /(?<!\]\()\[(\d+)\]/g,
      '<sup class="citation-badge">[$1]</sup>',
    )
  }, [message.content, isUser])

  return (
    <div className={`flex gap-2 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`w-6 h-6 rounded flex items-center justify-center flex-shrink-0 text-[10px] font-bold mt-0.5 ${
        isUser
          ? 'bg-[#58a6ff] text-white'
          : 'bg-[#21262d] text-[#8b949e] border border-[#30363d]'
      }`}>
        {isUser ? 'U' : 'AI'}
      </div>

      {/* Content */}
      <div className={`max-w-[85%] ${isUser ? 'text-right' : ''}`}>
        <div className={isUser ? 'bubble-user' : 'bubble-assistant'}>
          {message.content === '*[已中断]*' ? (
            <span className="text-[#8b949e] italic">{message.content}</span>
          ) : isUser ? (
            <div className="text-sm whitespace-pre-wrap break-words">
              {message.content}
            </div>
          ) : (
            <div className="text-sm break-words markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>
                {processedContent}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {/* Copy button for AI messages */}
        {!isUser && message.content !== '*[已中断]*' && (
          <button
            onClick={handleCopy}
            className="mt-1.5 flex items-center gap-1 px-2 py-1 text-xs rounded
                       text-[#484f58] hover:text-[#e6edf3] hover:bg-[#1c2128]
                       transition-colors border border-[#21262d]"
            title="复制回答"
          >
            {copied ? (
              <>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                已复制
              </>
            ) : (
              <>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                复制
              </>
            )}
          </button>
        )}
      </div>
    </div>
  )
}
