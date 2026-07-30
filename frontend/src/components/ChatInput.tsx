import { type FC, useState, useCallback, useRef, useEffect } from 'react'

interface ChatInputProps {
  onSend: (text: string) => void
  disabled?: boolean
}

export const ChatInput: FC<ChatInputProps> = ({ onSend, disabled }) => {
  const [text, setText] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // auto-resize
  useEffect(() => {
    const el = textareaRef.current
    if (el) {
      el.style.height = 'auto'
      el.style.height = Math.min(el.scrollHeight, 160) + 'px'
    }
  }, [text])

  const handleSend = useCallback(() => {
    if (!text.trim() || disabled) return
    onSend(text.trim())
    setText('')
    // reset height
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [text, disabled, onSend])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }, [handleSend])

  return (
    <div className="flex items-end gap-2">
      <textarea
        ref={textareaRef}
        value={text}
        onChange={e => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入药物名称或原辅料问题…"
        rows={1}
        disabled={disabled}
        className="ide-input resize-none min-h-[36px] max-h-[160px] py-[7px]"
      />
      <button
        onClick={handleSend}
        disabled={disabled || !text.trim()}
        className="btn-primary flex-shrink-0 self-end"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 19V5m0 0l-7 7m7-7l7 7" />
        </svg>
        发送
      </button>
    </div>
  )
}
