import { Phone, PhoneOff, Mic } from 'lucide-react';
import { useVoiceCall } from '../../hooks/useVoiceCall';

interface Props {
  agentId: string;
  disabled?: boolean;
}

export default function TestCallPanel({ agentId, disabled }: Props) {
  const { status, error, micLevel, start, stop } = useVoiceCall();

  const statusLabel: Record<string, string> = {
    idle: 'Ready to test',
    requesting: 'Starting call...',
    waiting: 'Waiting for worker...',
    connecting: 'Connecting...',
    active: 'Call active',
    error: 'Error',
  };

  const statusColor: Record<string, string> = {
    idle: 'text-slate-400',
    requesting: 'text-amber-400',
    waiting: 'text-amber-400',
    connecting: 'text-amber-400',
    active: 'text-emerald-400',
    error: 'text-red-400',
  };

  return (
    <div className="bg-slate-900 rounded-xl p-6 text-white flex flex-col items-center gap-4 min-h-[320px]">
      <h3 className="text-sm font-medium text-slate-400 uppercase tracking-wider">Test Call</h3>

      <div className="flex-1 flex flex-col items-center justify-center gap-4">
        {/* Status indicator */}
        <div className="relative">
          <div className={`w-20 h-20 rounded-full flex items-center justify-center ${
            status === 'active'
              ? 'bg-emerald-500/20 ring-2 ring-emerald-500'
              : status === 'error'
              ? 'bg-red-500/20 ring-2 ring-red-500'
              : 'bg-slate-800 ring-2 ring-slate-700'
          }`}>
            {status === 'active' ? (
              <Mic className="w-8 h-8 text-emerald-400" />
            ) : (
              <Phone className="w-8 h-8 text-slate-400" />
            )}
          </div>
          {status === 'active' && (
            <div className="absolute -bottom-1 -right-1 w-4 h-4 bg-emerald-500 rounded-full animate-pulse" />
          )}
        </div>

        <p className={`text-sm font-medium ${statusColor[status]}`}>
          {statusLabel[status]}
        </p>

        {error && <p className="text-xs text-red-400 text-center max-w-[200px]">{error}</p>}

        {/* Mic level bar */}
        {status === 'active' && (
          <div className="w-full max-w-[180px]">
            <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-emerald-500 rounded-full transition-all duration-75"
                style={{ width: `${micLevel}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Call button */}
      {status === 'idle' || status === 'error' ? (
        <button
          onClick={() => start(agentId)}
          disabled={disabled || !agentId}
          className="w-full py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed text-sm font-medium flex items-center justify-center gap-2 transition-colors"
        >
          <Phone className="w-4 h-4" />
          Start Test Call
        </button>
      ) : status === 'active' ? (
        <button
          onClick={stop}
          className="w-full py-2.5 rounded-lg bg-red-600 hover:bg-red-500 text-sm font-medium flex items-center justify-center gap-2 transition-colors"
        >
          <PhoneOff className="w-4 h-4" />
          End Call
        </button>
      ) : (
        <button disabled className="w-full py-2.5 rounded-lg bg-slate-700 text-slate-400 text-sm font-medium flex items-center justify-center gap-2">
          <Phone className="w-4 h-4 animate-pulse" />
          {statusLabel[status]}
        </button>
      )}

      <p className="text-xs text-slate-500 text-center">
        Use headphones to prevent echo
      </p>
    </div>
  );
}
