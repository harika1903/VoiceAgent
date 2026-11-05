import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Clock, Bot, User } from 'lucide-react';
import { calls, type TranscriptResponse } from '../services/api';
import { formatDuration, formatDateFull, formatTime } from '../utils/format';
import Badge from '../components/ui/Badge';

export default function CallDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [data, setData] = useState<TranscriptResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!id) return;
    calls
      .transcript(id)
      .then(setData)
      .catch((e) => setError(e.message || 'Failed to load transcript'))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="h-8 w-48 bg-zinc-800 rounded" />
        <div className="h-32 bg-zinc-800 rounded-xl" />
        <div className="space-y-3">
          {[...Array(6)].map((_, i) => (
            <div key={i} className={`h-12 bg-zinc-800 rounded-xl w-3/4 ${i % 2 ? '' : 'ml-auto'}`} />
          ))}
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="text-center py-20">
        <p className="text-zinc-400">{error || 'Call not found'}</p>
        <button onClick={() => navigate('/calls')} className="mt-4 text-sm text-indigo-400 hover:underline">
          Back to Call Logs
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl">
      {/* Back button */}
      <button
        onClick={() => navigate('/calls')}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-300"
      >
        <ArrowLeft size={16} /> Back to Call Logs
      </button>

      {/* Metadata card */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-5 mb-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4 mb-4">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Call {id?.slice(0, 8)}...</h2>
            <p className="text-sm text-zinc-400 mt-0.5">Agent: {data.agent_id}</p>
          </div>
          <Badge status={data.status} size="md" />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-zinc-400">Started</p>
            <p className="font-medium text-zinc-100">{formatDateFull(data.started_at)}</p>
          </div>
          <div>
            <p className="text-zinc-400">Ended</p>
            <p className="font-medium text-zinc-100">{formatDateFull(data.ended_at)}</p>
          </div>
          <div>
            <p className="text-zinc-400">Duration</p>
            <p className="font-medium text-zinc-100 flex items-center gap-1">
              <Clock size={14} /> {formatDuration(data.duration_secs)}
            </p>
          </div>
          <div>
            <p className="text-zinc-400">Turns</p>
            <p className="font-medium text-zinc-100">{data.turns.length}</p>
          </div>
        </div>

        {data.summary && (
          <div className="mt-4 pt-4 border-t border-zinc-800">
            <p className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-1">Summary</p>
            <p className="text-sm text-zinc-300 leading-relaxed">{data.summary}</p>
          </div>
        )}
      </div>

      {/* Transcript */}
      <div className="rounded-xl border border-zinc-800 bg-zinc-900 shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-zinc-800">
          <h3 className="text-sm font-semibold text-zinc-100">Transcript</h3>
        </div>

        {data.turns.length === 0 ? (
          <div className="px-5 py-12 text-center text-zinc-500">No transcript available</div>
        ) : (
          <div className="p-5 space-y-3">
            {data.turns.map((turn) => {
              const isUser = turn.role === 'user';
              return (
                <div key={turn.seq} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
                  <div className={`flex items-start gap-2.5 max-w-[75%] ${isUser ? 'flex-row-reverse' : ''}`}>
                    <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center ${
                      isUser ? 'bg-indigo-500/15' : 'bg-zinc-800'
                    }`}>
                      {isUser ? <User size={14} className="text-indigo-400" /> : <Bot size={14} className="text-zinc-400" />}
                    </div>
                    <div>
                      <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                        isUser
                          ? 'bg-indigo-600 text-white rounded-tr-md'
                          : 'bg-zinc-800 text-zinc-200 rounded-tl-md'
                      }`}>
                        {turn.text}
                        {turn.interrupted && (
                          <span className="ml-1 text-xs opacity-60">(interrupted)</span>
                        )}
                      </div>
                      <p className={`text-[11px] mt-1 ${isUser ? 'text-right' : ''} text-zinc-500`}>
                        {formatTime(turn.at)}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
