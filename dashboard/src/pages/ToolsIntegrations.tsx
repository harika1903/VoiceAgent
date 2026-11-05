import { Puzzle } from 'lucide-react';
import ComingSoon from '../components/ui/ComingSoon';

export default function ToolsIntegrations() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-zinc-100">Tools &amp; Integrations</h1>
        <p className="mt-1 text-sm text-zinc-400">Connect external tools and functions to your agents</p>
      </div>
      <ComingSoon
        icon={Puzzle}
        title="Tools & Integrations"
        description="Function calling and third-party integrations aren't implemented in the backend yet. This section will let agents call external tools once that API exists."
      />
    </div>
  );
}
