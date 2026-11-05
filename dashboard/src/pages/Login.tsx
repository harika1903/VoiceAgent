import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AudioLines, ArrowRight } from 'lucide-react'
import { setApiKey } from '../services/api'

export default function Login() {
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = key.trim()
    if (!trimmed) { setError('Please enter an API key'); return }

    setLoading(true)
    setError('')

    try {
      const res = await fetch('/v1/org', {
        headers: { 'Authorization': `Bearer ${trimmed}` },
      })
      if (!res.ok) {
        setError(res.status === 401 ? 'Invalid API key' : `Error: ${res.status}`)
        setLoading(false)
        return
      }
      setApiKey(trimmed)
      navigate('/', { replace: true })
    } catch {
      setError('Cannot reach the API server')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950 px-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-indigo-600 mb-4">
            <AudioLines className="w-7 h-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-zinc-100">VoiceAgent</h1>
          <p className="text-sm text-zinc-400 mt-1">AI Voice Agent Platform</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-zinc-900 rounded-xl shadow-sm border border-zinc-800 p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1.5">API Key</label>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="va_..."
              autoFocus
              className="w-full px-3.5 py-2.5 rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-100 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent placeholder:text-zinc-500"
            />
          </div>

          {error && (
            <p className="text-sm text-red-400 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Connecting...' : (
              <>Connect <ArrowRight className="w-4 h-4" /></>
            )}
          </button>
        </form>

        <p className="text-center text-xs text-zinc-500 mt-6">
          Find your API key in the server startup logs or Settings page.
        </p>
      </div>
    </div>
  )
}
