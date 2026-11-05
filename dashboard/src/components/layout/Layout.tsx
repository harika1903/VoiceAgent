import { useState } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Bot,
  BookOpen,
  Puzzle,
  Phone,
  PhoneCall,
  BarChart3,
  Key,
  Users,
  Settings as SettingsIcon,
  LogOut,
  Menu,
  X,
  AudioLines,
} from 'lucide-react'
import { clearApiKey } from '../../services/api'

const NAV = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard', end: true },
  { to: '/agents', icon: Bot, label: 'Agents' },
  { to: '/kb', icon: BookOpen, label: 'Knowledge Base' },
  { to: '/tools', icon: Puzzle, label: 'Tools & Integrations' },
  { to: '/phone-numbers', icon: Phone, label: 'Phone Numbers' },
  { to: '/calls', icon: PhoneCall, label: 'Call History' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/keys', icon: Key, label: 'API Keys' },
  { to: '/team', icon: Users, label: 'Team Members' },
  { to: '/settings', icon: SettingsIcon, label: 'Settings' },
]

const TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/agents': 'Agents',
  '/kb': 'Knowledge Base',
  '/tools': 'Tools & Integrations',
  '/phone-numbers': 'Phone Numbers',
  '/calls': 'Call History',
  '/analytics': 'Analytics',
  '/keys': 'API Keys',
  '/team': 'Team Members',
  '/settings': 'Settings',
}

function getTitle(pathname: string): string {
  if (pathname.startsWith('/agents/')) return 'Agent Builder'
  if (pathname.startsWith('/calls/')) return 'Call Detail'
  return TITLES[pathname] || 'Dashboard'
}

export default function Layout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const title = getTitle(location.pathname)

  function handleLogout() {
    clearApiKey()
    navigate('/login')
  }

  const sidebar = (
    <div className="flex flex-col h-full bg-[#111113] text-zinc-300">
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-white/10">
        <AudioLines className="w-6 h-6 text-indigo-400" />
        <span className="text-[15px] font-semibold tracking-tight text-white">VoiceAgent</span>
      </div>

      <nav className="flex-1 px-2.5 py-3 space-y-0.5 overflow-y-auto">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={() => setSidebarOpen(false)}
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2 rounded-lg text-[13.5px] font-medium transition-colors ${
                isActive
                  ? 'bg-indigo-600 text-white'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-900/5'
              }`
            }
          >
            <item.icon className="w-[17px] h-[17px] shrink-0" />
            <span className="truncate">{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="px-2.5 py-3 border-t border-white/10">
        <button
          onClick={handleLogout}
          className="flex items-center gap-2.5 px-3 py-2 w-full rounded-lg text-[13.5px] font-medium text-zinc-400 hover:text-white hover:bg-zinc-900/5 transition-colors"
        >
          <LogOut className="w-[17px] h-[17px]" />
          Logout
        </button>
      </div>
    </div>
  )

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex lg:w-60 lg:flex-shrink-0">
        {sidebar}
      </aside>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="fixed inset-0 bg-black/50" onClick={() => setSidebarOpen(false)} />
          <div className="fixed inset-y-0 left-0 w-60 z-50">{sidebar}</div>
        </div>
      )}

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="flex items-center gap-4 px-4 lg:px-8 h-16 bg-zinc-900 border-b border-zinc-800 flex-shrink-0">
          <button
            className="lg:hidden p-1.5 rounded-md hover:bg-zinc-800"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? <X className="w-5 h-5 text-zinc-300" /> : <Menu className="w-5 h-5 text-zinc-300" />}
          </button>
          <h1 className="text-lg font-semibold text-zinc-100">{title}</h1>
        </header>
        <main className="flex-1 overflow-y-auto p-4 lg:p-8 bg-zinc-950">
          {children}
        </main>
      </div>
    </div>
  )
}
