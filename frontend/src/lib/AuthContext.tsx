import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { getStoredToken, setStoredToken, clearStoredToken, login as apiLogin, checkAuth } from './api'

interface AuthState {
  isLoggedIn: boolean
  username: string
  loading: boolean
  login: (username: string, password: string) => Promise<{ ok: boolean; message: string }>
  logout: () => void
}

const AuthContext = createContext<AuthState>({
  isLoggedIn: false,
  username: '',
  loading: true,
  login: async () => ({ ok: false, message: '' }),
  logout: () => {},
})

export const useAuth = () => useContext(AuthContext)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [username, setUsername] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // 启动时检查既有 token
    const token = getStoredToken()
    if (token) {
      checkAuth().then(valid => {
        if (valid) {
          setIsLoggedIn(true)
          setUsername('admin')
        } else {
          clearStoredToken()
        }
        setLoading(false)
      })
    } else {
      setLoading(false)
    }
  }, [])

  const login = useCallback(async (uname: string, pwd: string) => {
    const result = await apiLogin(uname, pwd)
    if (result.ok) {
      setStoredToken(result.token)
      setIsLoggedIn(true)
      setUsername(result.username)
    }
    return { ok: result.ok, message: result.message }
  }, [])

  const logout = useCallback(() => {
    clearStoredToken()
    setIsLoggedIn(false)
    setUsername('')
  }, [])

  return (
    <AuthContext.Provider value={{ isLoggedIn, username, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
