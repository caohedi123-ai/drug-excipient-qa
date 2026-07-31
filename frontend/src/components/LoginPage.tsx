import React, { useState } from 'react'
import { useAuth } from '../lib/AuthContext'

const LoginPage: React.FC = () => {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [errMsg, setErrMsg] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) {
      setErrMsg('请输入用户名和密码')
      return
    }
    setLoading(true)
    setErrMsg('')
    const result = await login(username, password)
    setLoading(false)
    if (!result.ok) {
      setErrMsg(result.message)
    }
  }

  return (
    <div style={styles.wrapper}>
      {/* 背景层 */}
      <div style={styles.bg}>
        <div style={styles.gradient1}></div>
        <div style={styles.gradient2}></div>
        <div style={styles.grid}></div>
      </div>

      {/* 登录卡片 */}
      <div style={styles.card}>
        {/* Logo 区域 */}
        <div style={styles.logoArea}>
          <div style={styles.logoHex}>
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.5">
              <path d="M12 2L3 7v3c0 5.5 3.8 10.7 9 12 5.2-1.3 9-6.5 9-12V7l-9-5z" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <h1 style={styles.title}>药物原辅料知识库</h1>
          <p style={styles.subtitle}>Pharmaceutical Excipient &amp; API Intelligence</p>
        </div>

        {/* 表单 */}
        <form onSubmit={handleSubmit} style={styles.form}>
          <div style={styles.inputGroup}>
            <label style={styles.label}>用户名</label>
            <div style={styles.inputWrapper}>
              <svg style={styles.inputIcon} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8b949e" strokeWidth="1.5">
                <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
              </svg>
              <input
                style={styles.input}
                type="text"
                placeholder="请输入用户名"
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="username"
              />
            </div>
          </div>
          <div style={styles.inputGroup}>
            <label style={styles.label}>密码</label>
            <div style={styles.inputWrapper}>
              <svg style={styles.inputIcon} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#8b949e" strokeWidth="1.5">
                <rect x="3" y="11" width="18" height="11" rx="2"/>
                <path d="M7 11V7a5 5 0 0110 0v4"/>
              </svg>
              <input
                style={styles.input}
                type="password"
                placeholder="请输入密码"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
          </div>

          {errMsg && (
            <div style={styles.error}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f85149" strokeWidth="2">
                <circle cx="12" cy="12" r="10"/>
                <path d="M15 9l-6 6M9 9l6 6"/>
              </svg>
              {errMsg}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            style={{
              ...styles.btn,
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? (
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ animation: 'spin 1s linear infinite' }}>
                  <circle cx="8" cy="8" r="6" stroke="white" strokeWidth="2" strokeDasharray="28" strokeLinecap="round"/>
                </svg>
                登录中...
              </span>
            ) : '登 录'}
          </button>
        </form>

        {/* 底部提示 */}
        <p style={styles.footer}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#484f58" strokeWidth="2">
            <rect x="3" y="11" width="18" height="11" rx="2"/>
            <path d="M7 11V7a5 5 0 0110 0v4"/>
          </svg>
          受保护系统，请使用授权账号登录
        </p>
      </div>
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    width: '100vw',
    height: '100vh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    position: 'relative',
    overflow: 'hidden',
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
    background: '#0d1117',
  },
  bg: {
    position: 'absolute',
    inset: 0,
    overflow: 'hidden',
  },
  gradient1: {
    position: 'absolute',
    width: 600,
    height: 600,
    borderRadius: '50%',
    background: 'radial-gradient(circle, rgba(88,166,255,0.12) 0%, transparent 70%)',
    top: '-120px',
    right: '-100px',
  },
  gradient2: {
    position: 'absolute',
    width: 500,
    height: 500,
    borderRadius: '50%',
    background: 'radial-gradient(circle, rgba(210,153,34,0.1) 0%, transparent 70%)',
    bottom: '-100px',
    left: '-80px',
  },
  grid: {
    position: 'absolute',
    inset: 0,
    backgroundImage: 'linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)',
    backgroundSize: '60px 60px',
  },
  card: {
    position: 'relative',
    width: 420,
    background: 'rgba(22,27,34,0.85)',
    backdropFilter: 'blur(24px)',
    border: '1px solid rgba(48,54,61,0.6)',
    borderRadius: 16,
    padding: '40px 36px 32px',
    boxShadow: '0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(88,166,255,0.06)',
  },
  logoArea: {
    textAlign: 'center',
    marginBottom: 32,
  },
  logoHex: {
    width: 56,
    height: 56,
    borderRadius: 14,
    background: 'linear-gradient(135deg, #1f6feb 0%, #58a6ff 100%)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    margin: '0 auto 16px',
    boxShadow: '0 4px 16px rgba(31,111,235,0.3)',
  },
  title: {
    color: '#e6edf3',
    fontSize: 22,
    fontWeight: 600,
    margin: 0,
    letterSpacing: '0.02em',
  },
  subtitle: {
    color: '#484f58',
    fontSize: 12,
    marginTop: 6,
    fontWeight: 400,
    letterSpacing: '0.05em',
    textTransform: 'uppercase' as const,
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 18,
  },
  inputGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  label: {
    color: '#8b949e',
    fontSize: 12,
    fontWeight: 500,
  },
  inputWrapper: {
    display: 'flex',
    alignItems: 'center',
    background: '#0d1117',
    border: '1px solid #21262d',
    borderRadius: 8,
    padding: '0 12px',
    transition: 'border-color 0.2s',
  },
  inputIcon: {
    flexShrink: 0,
    marginRight: 8,
  },
  input: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    color: '#e6edf3',
    fontSize: 14,
    padding: '11px 0',
    outline: 'none',
    width: '100%',
  },
  error: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    color: '#f85149',
    fontSize: 12,
    background: 'rgba(248,81,73,0.08)',
    border: '1px solid rgba(248,81,73,0.2)',
    borderRadius: 6,
    padding: '8px 12px',
  },
  btn: {
    width: '100%',
    padding: '12px 0',
    background: 'linear-gradient(135deg, #1f6feb 0%, #388bfd 100%)',
    color: 'white',
    border: 'none',
    borderRadius: 8,
    fontSize: 15,
    fontWeight: 600,
    cursor: 'pointer',
    letterSpacing: '0.05em',
    transition: 'all 0.2s',
    marginTop: 4,
  },
  footer: {
    textAlign: 'center',
    color: '#484f58',
    fontSize: 11,
    marginTop: 24,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
}

export default LoginPage
