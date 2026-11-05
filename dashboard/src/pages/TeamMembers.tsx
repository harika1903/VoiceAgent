import { Users } from 'lucide-react';
import ComingSoon from '../components/ui/ComingSoon';

export default function TeamMembers() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-zinc-100">Team Members</h1>
        <p className="mt-1 text-sm text-zinc-400">Invite teammates and manage access to your organization</p>
      </div>
      <ComingSoon
        icon={Users}
        title="Team Members"
        description="Multi-user access and roles aren't implemented in the backend yet. Each organization currently shares a single set of API keys — see the API Keys page."
      />
    </div>
  );
}
