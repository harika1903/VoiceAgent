import { Phone } from 'lucide-react';
import ComingSoon from '../components/ui/ComingSoon';

export default function PhoneNumbers() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-zinc-100">Phone Numbers</h1>
        <p className="mt-1 text-sm text-zinc-400">Attach phone numbers to agents for inbound and outbound calls</p>
      </div>
      <ComingSoon
        icon={Phone}
        title="Phone Numbers"
        description="Telephony and number provisioning aren't implemented in the backend yet. For now, agents can only be tested over a browser WebSocket call from the Agent Builder."
      />
    </div>
  );
}
