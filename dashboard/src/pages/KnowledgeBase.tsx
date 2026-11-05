import { useEffect, useState } from 'react';
import { BookOpen, Search, Trash2, Upload, X } from 'lucide-react';
import { kb, type KBDocument, type KBStats } from '../services/api';
import { useToast } from '../components/ui/Toast';
import Modal from '../components/ui/Modal';

export default function KnowledgeBase() {
  const { toast } = useToast();
  const [docs, setDocs] = useState<KBDocument[]>([]);
  const [stats, setStats] = useState<KBStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<KBDocument[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadText, setUploadText] = useState('');
  const [uploadId, setUploadId] = useState('');
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const [d, s] = await Promise.all([kb.list(), kb.stats()]);
      setDocs(d);
      setStats(s);
    } catch (e) {
      toast('error', 'Failed to load knowledge base');
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const handleSearch = async () => {
    if (!searchQuery.trim()) { setSearchResults(null); return; }
    setSearching(true);
    try {
      const res = await kb.search(searchQuery.trim(), 5);
      setSearchResults(res.results);
    } catch (e: unknown) {
      toast('error', e instanceof Error ? e.message : 'Search failed');
    } finally {
      setSearching(false);
    }
  };

  const handleUpload = async () => {
    if (!uploadText.trim()) return;
    setUploading(true);
    try {
      const docId = uploadId.trim() || `doc-${Date.now()}`;
      const result = await kb.upload([{ id: docId, text: uploadText.trim() }]);
      toast('success', `Added ${result.added} document(s). Total: ${result.total}`);
      setShowUpload(false);
      setUploadText('');
      setUploadId('');
      refresh();
    } catch (e: unknown) {
      toast('error', e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (docId: string) => {
    setDeleting(docId);
    try {
      await kb.delete(docId);
      toast('success', 'Document deleted');
      setDocs((prev) => prev.filter((d) => d.id !== docId));
    } catch (e: unknown) {
      toast('error', e instanceof Error ? e.message : 'Delete failed');
    } finally {
      setDeleting(null);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-800 border-t-indigo-600" />
      </div>
    );
  }

  const displayDocs = searchResults ?? docs;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-zinc-100">Knowledge Base</h1>
          <p className="mt-1 text-sm text-zinc-400">
            {stats ? `${stats.size} documents indexed` : 'Manage documents for agent retrieval'}
          </p>
        </div>
        <button
          onClick={() => setShowUpload(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-indigo-700"
        >
          <Upload size={18} />
          Add Document
        </button>
      </div>

      {/* Search */}
      <div className="mb-6 flex gap-2">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            placeholder="Search knowledge base..."
            className="w-full rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-100 placeholder:text-zinc-500 py-2.5 pl-10 pr-3 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
          {searchResults && (
            <button
              onClick={() => { setSearchResults(null); setSearchQuery(''); }}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-400"
            >
              <X size={16} />
            </button>
          )}
        </div>
        <button
          onClick={handleSearch}
          disabled={searching}
          className="rounded-lg border border-zinc-700 px-4 py-2.5 text-sm font-medium text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
        >
          {searching ? 'Searching...' : 'Search'}
        </button>
      </div>

      {searchResults && (
        <p className="mb-4 text-sm text-zinc-400">
          {searchResults.length} result{searchResults.length !== 1 ? 's' : ''} for &ldquo;{searchQuery}&rdquo;
        </p>
      )}

      {/* Document List */}
      {displayDocs.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-700 py-16">
          <BookOpen size={48} className="mb-4 text-zinc-500" />
          <h3 className="text-lg font-semibold text-zinc-300">
            {searchResults ? 'No results found' : 'No documents yet'}
          </h3>
          <p className="mb-6 mt-1 text-sm text-zinc-400">
            {searchResults ? 'Try a different search query' : 'Upload documents to build your knowledge base'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {displayDocs.map((doc) => (
            <div key={doc.id} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 shadow-sm">
              <div className="mb-2 flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-sm font-semibold text-zinc-100">{doc.id}</h3>
                  {doc.metadata && Object.keys(doc.metadata).length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {Object.entries(doc.metadata).slice(0, 3).map(([k, v]) => (
                        <span key={k} className="rounded bg-zinc-800 px-1.5 py-0.5 text-xs text-zinc-400">
                          {k}: {String(v)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => handleDelete(doc.id)}
                  disabled={deleting === doc.id}
                  className="shrink-0 rounded-lg p-1.5 text-zinc-500 hover:bg-red-500/10 hover:text-red-400 disabled:opacity-50"
                >
                  <Trash2 size={16} />
                </button>
              </div>
              <p className="line-clamp-3 text-sm text-zinc-400">{doc.text}</p>
            </div>
          ))}
        </div>
      )}

      {/* Upload Modal */}
      <Modal open={showUpload} onClose={() => setShowUpload(false)} title="Add Document">
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">Document ID (optional)</label>
            <input
              type="text"
              value={uploadId}
              onChange={(e) => setUploadId(e.target.value)}
              placeholder="Auto-generated if empty"
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-100 placeholder:text-zinc-500 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-zinc-300">Content</label>
            <textarea
              value={uploadText}
              onChange={(e) => setUploadText(e.target.value)}
              rows={8}
              placeholder="Paste document content here..."
              className="w-full rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-100 placeholder:text-zinc-500 px-3 py-2 text-sm focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setShowUpload(false)}
              className="rounded-lg border border-zinc-700 px-4 py-2 text-sm font-medium text-zinc-300 hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              onClick={handleUpload}
              disabled={uploading || !uploadText.trim()}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {uploading ? 'Uploading...' : 'Add Document'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
