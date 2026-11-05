import { Navigate, Route, Routes } from 'react-router-dom'
import { hasApiKey } from './services/api'
import Layout from './components/layout/Layout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Agents from './pages/Agents'
import AgentBuilder from './pages/AgentBuilder'
import Calls from './pages/Calls'
import CallDetail from './pages/CallDetail'
import KnowledgeBase from './pages/KnowledgeBase'
import Settings from './pages/Settings'
import Analytics from './pages/Analytics'
import ApiKeys from './pages/ApiKeys'
import ToolsIntegrations from './pages/ToolsIntegrations'
import PhoneNumbers from './pages/PhoneNumbers'
import TeamMembers from './pages/TeamMembers'

function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!hasApiKey()) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <Layout>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/agents" element={<Agents />} />
                <Route path="/agents/:id" element={<AgentBuilder />} />
                <Route path="/calls" element={<Calls />} />
                <Route path="/calls/:id" element={<CallDetail />} />
                <Route path="/kb" element={<KnowledgeBase />} />
                <Route path="/tools" element={<ToolsIntegrations />} />
                <Route path="/phone-numbers" element={<PhoneNumbers />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/keys" element={<ApiKeys />} />
                <Route path="/team" element={<TeamMembers />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </Layout>
          </RequireAuth>
        }
      />
    </Routes>
  )
}
