import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Database, FolderOpen, Search, Plus, Trash2, Upload,
  RefreshCw, Loader2, CheckCircle, AlertCircle, ChevronRight,
  ChevronDown, FileText, HardDrive, Layers, X, Server,
  Eye, Zap, Play, Hash, Pencil, Check, MoreVertical,
  CloudUpload, ArrowRight
} from 'lucide-react';
import {
  kbGetStatus, kbListDatabases, kbListCollections, kbListIndexes,
  kbGetStats, kbCreateIndex, kbDeleteIndex, kbIngestFile,
  kbDeleteFile, kbCreateCollection, kbBrowseDocuments, kbListAllIndexes,
  kbVectorSearch, kbDeleteCollection, kbRenameCollection
} from '../services/api';
import { useLoading } from '../context/LoadingContext';

interface DbInfo {
  name: string;
  collections: string[];
  collection_count: number;
}

interface CollectionInfo {
  name: string;
  document_count: number;
  size_bytes: number;
  size_display: string;
}

interface IndexInfo {
  name: string;
  type: string;
  collection?: string;
  status?: string;
  fields?: { path: string; type: string; numDimensions?: number; similarity?: string }[];
  keys?: Record<string, number>;
  unique?: boolean;
  queryable?: boolean;
}

interface CollStats {
  document_count: number;
  files: string[];
  file_count: number;
  sample_document: Record<string, string> | null;
}

interface DocumentData {
  documents: Record<string, any>[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

function Modal({ open, onClose, children, size = 'md' }: { open: boolean; onClose: () => void; children: React.ReactNode; size?: 'sm' | 'md' | 'lg' }) {
  if (!open) return null;
  const widthClass = size === 'sm' ? 'max-w-md' : size === 'lg' ? 'max-w-2xl' : 'max-w-lg';
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-gray-900/40 dark:bg-black/70 backdrop-blur-md kb-fade-in" />
      <div
        className={`relative ${widthClass} w-full overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.1] bg-white dark:bg-zinc-900/95 shadow-2xl shadow-black/50 ring-1 ring-white/[0.06] backdrop-blur-xl kb-slide-up`}
        onClick={e => e.stopPropagation()}
      >
        <div className="pointer-events-none absolute -right-24 -top-24 h-48 w-48 rounded-full bg-orange-500/15 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-28 -left-20 h-44 w-44 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="relative">{children}</div>
      </div>
    </div>
  );
}

export default function KnowledgeBaseTab() {
  const { withLoader } = useLoading();
  const [connected, setConnected] = useState<boolean | null>(null);
  const [statusMsg, setStatusMsg] = useState('');
  const [databases, setDatabases] = useState<DbInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDb, setSelectedDb] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<'collections' | 'indexes'>('collections');

  const [collections, setCollections] = useState<CollectionInfo[]>([]);
  const [loadingCollections, setLoadingCollections] = useState(false);

  const [searchIndexes, setSearchIndexes] = useState<IndexInfo[]>([]);
  const [regularIndexes, setRegularIndexes] = useState<IndexInfo[]>([]);
  const [loadingIndexes, setLoadingIndexes] = useState(false);
  const [showRegularIndexes, setShowRegularIndexes] = useState(false);

  const [selectedColl, setSelectedColl] = useState<string | null>(null);
  const [collStats, setCollStats] = useState<CollStats | null>(null);
  const [collIndexes, setCollIndexes] = useState<IndexInfo[]>([]);

  const [docData, setDocData] = useState<DocumentData | null>(null);
  const [docPage, setDocPage] = useState(1);
  const [docSearch, setDocSearch] = useState('');
  const [docSearchInput, setDocSearchInput] = useState('');
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [expandedDoc, setExpandedDoc] = useState<string | null>(null);

  const [showCreateIndex, setShowCreateIndex] = useState(false);
  const [newIndexName, setNewIndexName] = useState('vector_index');
  const [newIndexDimensions, setNewIndexDimensions] = useState(384);
  const [newIndexSimilarity, setNewIndexSimilarity] = useState('cosine');
  const [newIndexCollection, setNewIndexCollection] = useState('');
  const [creatingIndex, setCreatingIndex] = useState(false);

  const [showCreateCollection, setShowCreateCollection] = useState(false);
  const [newDbName, setNewDbName] = useState('');
  const [newCollName, setNewCollName] = useState('');
  const [creatingCollection, setCreatingCollection] = useState(false);

  const [ingesting, setIngesting] = useState(false);
  const [ingestProjectId, setIngestProjectId] = useState('');
  const [showUploadPanel, setShowUploadPanel] = useState(false);
  const [ingestProgress, setIngestProgress] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const [queryIndex, setQueryIndex] = useState<IndexInfo | null>(null);
  const [queryText, setQueryText] = useState('');
  const [queryLimit, setQueryLimit] = useState(10);
  const [queryResults, setQueryResults] = useState<any[] | null>(null);
  const [queryLoading, setQueryLoading] = useState(false);
  const [expandedResult, setExpandedResult] = useState<string | null>(null);

  const [renamingColl, setRenamingColl] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [collMenuOpen, setCollMenuOpen] = useState<string | null>(null);

  const [dragOver, setDragOver] = useState(false);

  useEffect(() => {
    if (actionMsg) {
      const timer = setTimeout(() => setActionMsg(null), 6000);
      return () => clearTimeout(timer);
    }
  }, [actionMsg]);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await withLoader('Connecting to Knowledge Base...', async () => {
        const status = await kbGetStatus();
        setConnected(status.connected);
        setStatusMsg(status.message);
        if (status.connected) {
          const dbData = await kbListDatabases();
          setDatabases(dbData.databases || []);
        }
      });
    } catch (e: any) {
      setConnected(false);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const selectDatabase = useCallback(async (dbName: string) => {
    if (selectedDb === dbName) return;
    setSelectedDb(dbName);
    setSelectedColl(null);
    setCollStats(null);
    setCollIndexes([]);
    setDocData(null);
    setDocPage(1);
    setDocSearch('');
    setDocSearchInput('');
    setQueryIndex(null);
    setQueryResults(null);

    setLoadingCollections(true);
    setLoadingIndexes(true);
    try {
      const [collData, idxData] = await withLoader('Loading database contents...', () => Promise.all([
        kbListCollections(dbName),
        kbListAllIndexes(dbName),
      ]));
      setCollections(collData.collections || []);
      setSearchIndexes(idxData.search_indexes || []);
      setRegularIndexes(idxData.regular_indexes || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoadingCollections(false);
      setLoadingIndexes(false);
    }
  }, [selectedDb]);

  const selectCollection = useCallback(async (collName: string) => {
    if (!selectedDb) return;
    setSelectedColl(collName);
    setDocPage(1);
    setDocSearch('');
    setDocSearchInput('');
    setExpandedDoc(null);
    setLoadingDocs(true);
    try {
      const [statsData, idxData, docsData] = await withLoader('Loading collection data...', () => Promise.all([
        kbGetStats(selectedDb, collName),
        kbListIndexes(selectedDb, collName),
        kbBrowseDocuments(selectedDb, collName, 1, 20, ''),
      ]));
      setCollStats(statsData);
      setCollIndexes(idxData.indexes || []);
      setDocData(docsData);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoadingDocs(false);
    }
  }, [selectedDb]);

  const loadDocuments = useCallback(async (page: number, search: string) => {
    if (!selectedDb || !selectedColl) return;
    setLoadingDocs(true);
    try {
      const data = await withLoader('Loading documents...', () => kbBrowseDocuments(selectedDb!, selectedColl!, page, 20, search));
      setDocData(data);
      setDocPage(page);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoadingDocs(false);
    }
  }, [selectedDb, selectedColl]);

  const handleDocSearch = () => {
    setDocSearch(docSearchInput);
    loadDocuments(1, docSearchInput);
  };

  const handleCreateIndex = async () => {
    const targetColl = selectedColl || newIndexCollection;
    if (!selectedDb || !targetColl) return;
    setCreatingIndex(true);
    setActionMsg(null);
    try {
      const result = await withLoader('Creating search index...', () => kbCreateIndex({
        db_name: selectedDb,
        collection_name: targetColl,
        index_name: newIndexName,
        dimensions: newIndexDimensions,
        similarity: newIndexSimilarity,
      }));
      setActionMsg({ type: 'success', text: result.message });
      setShowCreateIndex(false);
      const idxData = await kbListAllIndexes(selectedDb);
      setSearchIndexes(idxData.search_indexes || []);
      setRegularIndexes(idxData.regular_indexes || []);
      if (selectedColl) {
        const collIdx = await kbListIndexes(selectedDb, selectedColl);
        setCollIndexes(collIdx.indexes || []);
      }
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e.message });
    } finally {
      setCreatingIndex(false);
    }
  };

  const handleDeleteCollection = async (collName: string) => {
    if (!selectedDb) return;
    if (!confirm(`Delete collection "${collName}" and all its documents? This cannot be undone.`)) return;
    setCollMenuOpen(null);
    try {
      await withLoader('Deleting collection...', () => kbDeleteCollection(selectedDb!, collName));
      setActionMsg({ type: 'success', text: `Collection "${collName}" deleted` });
      if (selectedColl === collName) {
        setSelectedColl(null);
        setCollStats(null);
        setCollIndexes([]);
        setDocData(null);
      }
      const [collData, idxData] = await Promise.all([
        kbListCollections(selectedDb),
        kbListAllIndexes(selectedDb),
      ]);
      setCollections(collData.collections || []);
      setSearchIndexes(idxData.search_indexes || []);
      setRegularIndexes(idxData.regular_indexes || []);
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e.message });
    }
  };

  const handleRenameCollection = async (oldName: string) => {
    if (!selectedDb || !renameValue.trim() || renameValue.trim() === oldName) {
      setRenamingColl(null);
      return;
    }
    try {
      await withLoader('Renaming collection...', () => kbRenameCollection(selectedDb!, oldName, renameValue.trim()));
      setActionMsg({ type: 'success', text: `Collection renamed to "${renameValue.trim()}"` });
      setRenamingColl(null);
      if (selectedColl === oldName) setSelectedColl(renameValue.trim());
      const [collData, idxData] = await Promise.all([
        kbListCollections(selectedDb),
        kbListAllIndexes(selectedDb),
      ]);
      setCollections(collData.collections || []);
      setSearchIndexes(idxData.search_indexes || []);
      setRegularIndexes(idxData.regular_indexes || []);
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e.message });
      setRenamingColl(null);
    }
  };

  const handleDeleteIndex = async (indexName: string, collName: string) => {
    if (!selectedDb) return;
    if (!confirm(`Delete search index "${indexName}"? This cannot be undone.`)) return;
    try {
      await withLoader('Deleting index...', () => kbDeleteIndex(selectedDb!, collName, indexName));
      setActionMsg({ type: 'success', text: `Index "${indexName}" deleted` });
      const idxData = await kbListAllIndexes(selectedDb);
      setSearchIndexes(idxData.search_indexes || []);
      setRegularIndexes(idxData.regular_indexes || []);
      if (selectedColl) {
        const collIdx = await kbListIndexes(selectedDb, selectedColl);
        setCollIndexes(collIdx.indexes || []);
      }
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e.message });
    }
  };

  const handleVectorSearch = async () => {
    if (!selectedDb || !queryIndex || !queryText.trim()) return;
    setQueryLoading(true);
    setQueryResults(null);
    setExpandedResult(null);
    try {
      const result = await withLoader('Running vector search...', () => kbVectorSearch({
        db_name: selectedDb!,
        collection_name: queryIndex!.collection!,
        query: queryText.trim(),
        index_name: queryIndex!.name,
        limit: queryLimit,
      }));
      setQueryResults(result.results || []);
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e.message });
    } finally {
      setQueryLoading(false);
    }
  };

  const processFile = async (file: File) => {
    if (!selectedDb) return;

    const projectId = ingestProjectId.trim();
    if (!projectId) {
      setActionMsg({ type: 'error', text: 'Please enter a Project ID before uploading' });
      if (fileInputRef.current) fileInputRef.current.value = '';
      return;
    }

    setIngesting(true);
    setIngestProgress('Reading file...');
    setActionMsg(null);
    try {
      const b64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = reader.result as string;
          resolve(result.split(',')[1]);
        };
        reader.onerror = reject;
        reader.readAsDataURL(file);
      });

      setIngestProgress('Parsing & extracting text, captioning images, chunking, embedding...');
      const ext = file.name.split('.').pop() || '';
      const result = await withLoader('Ingesting file...', () => kbIngestFile({
        db_name: selectedDb!,
        project_id: projectId,
        file_name: file.name,
        file_type: ext,
        file_content_b64: b64,
      }));

      const details = [
        `${result.chunks} chunks`,
        result.image_count ? `${result.image_count} images found` : null,
        result.extracted_images ? `${result.extracted_images} extracted` : null,
        result.captioned_images ? `${result.captioned_images} captioned via Gemini` : null,
        result.embedding_dimensions ? `${result.embedding_dimensions}d embeddings` : null,
      ].filter(Boolean).join(', ');

      setActionMsg({
        type: 'success',
        text: `"${file.name}" ingested into ${result.documents_collection} + ${result.chunks_collection} (${details})`
      });

      const collRefresh = await kbListCollections(selectedDb);
      setCollections(collRefresh.collections || []);
      if (selectedColl) {
        const [statsData, docsData] = await Promise.all([
          kbGetStats(selectedDb, selectedColl),
          kbBrowseDocuments(selectedDb, selectedColl, 1, 20, ''),
        ]);
        setCollStats(statsData);
        setDocData(docsData);
        setDocPage(1);
        setDocSearch('');
        setDocSearchInput('');
      }
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e.message });
    } finally {
      setIngesting(false);
      setIngestProgress('');
      setShowUploadPanel(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedDb) return;
    processFile(file);
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) processFile(file);
  }, [selectedDb, ingestProjectId, selectedColl]);

  const handleDeleteFile = async (fileName: string) => {
    if (!selectedDb || !selectedColl) return;
    if (!confirm(`Delete all chunks for "${fileName}"?`)) return;
    try {
      const result = await withLoader('Deleting file...', () => kbDeleteFile(selectedDb!, selectedColl!, fileName));
      setActionMsg({ type: 'success', text: result.message });
      const [statsData, docsData] = await Promise.all([
        kbGetStats(selectedDb, selectedColl),
        kbBrowseDocuments(selectedDb, selectedColl, 1, 20, ''),
      ]);
      setCollStats(statsData);
      setDocData(docsData);
      setDocPage(1);
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e.message });
    }
  };

  const handleCreateCollection = async () => {
    if (!newDbName.trim() || !newCollName.trim()) return;
    setCreatingCollection(true);
    setActionMsg(null);
    try {
      const result = await withLoader('Creating collection...', () => kbCreateCollection({ db_name: newDbName.trim(), collection_name: newCollName.trim() }));
      setActionMsg({ type: 'success', text: result.message });
      setShowCreateCollection(false);
      setNewDbName('');
      setNewCollName('');
      const dbData = await kbListDatabases();
      setDatabases(dbData.databases || []);
      if (selectedDb === newDbName.trim()) {
        const collData = await kbListCollections(selectedDb);
        setCollections(collData.collections || []);
      }
    } catch (e: any) {
      setActionMsg({ type: 'error', text: e.message });
    } finally {
      setCreatingCollection(false);
    }
  };

  // --- Loading state ---
  if (loading) {
    return (
      <div className="relative flex h-[calc(100vh-120px)] items-center justify-center overflow-hidden bg-gradient-to-b from-white dark:from-zinc-950 via-gray-50 dark:via-zinc-950 to-gray-50 dark:to-black">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_80%_50%_at_50%_-20%,rgba(249,115,22,0.12),transparent)]" />
        <div className="text-center kb-fade-in relative">
          <div className="relative mx-auto mb-6 h-20 w-20">
            <div className="absolute inset-0 rounded-2xl bg-orange-500/25 blur-xl" />
            <div className="relative flex h-20 w-20 items-center justify-center rounded-2xl border border-orange-500/30 bg-gradient-to-br from-orange-500/20 to-orange-600/5 ring-1 ring-orange-500/20">
              <Database className="h-9 w-9 text-orange-400" />
            </div>
            <Loader2 className="absolute -bottom-1 -right-1 h-6 w-6 animate-spin text-orange-400/80" />
          </div>
          <p className="text-sm font-medium text-gray-700 dark:text-zinc-300">Connecting to MongoDB Atlas</p>
          <p className="mt-1 text-xs text-zinc-500">Vector indexes, collections, and ingestion</p>
        </div>
      </div>
    );
  }

  // --- Not connected state ---
  if (!connected) {
    return (
      <div className="relative flex h-[calc(100vh-120px)] items-center justify-center overflow-hidden bg-gradient-to-b from-white dark:from-zinc-950 via-gray-50 dark:via-zinc-950 to-gray-50 dark:to-black p-6">
        <div className="pointer-events-none absolute -right-32 top-1/4 h-72 w-72 rounded-full bg-red-500/5 blur-3xl" />
        <div className="relative w-full max-w-md kb-slide-up">
          <div className="relative overflow-hidden rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-gradient-to-br from-white dark:from-zinc-900/95 via-gray-50 dark:via-zinc-950/90 to-gray-50 dark:to-zinc-950 p-8 text-center shadow-2xl shadow-black/40 ring-1 ring-white/[0.05]">
            <div className="pointer-events-none absolute -left-20 -top-20 h-40 w-40 rounded-full bg-orange-500/10 blur-3xl" />
            <div className="relative mx-auto mb-5 flex h-20 w-20 items-center justify-center rounded-2xl border border-red-500/25 bg-red-500/10 ring-1 ring-red-500/15">
              <Database className="h-10 w-10 text-red-400" />
            </div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-red-400/90">Data layer</p>
            <h3 className="font-heading mt-2 text-xl font-bold tracking-tight text-gray-900 dark:text-white">MongoDB not connected</h3>
            <p className="mt-3 text-sm leading-relaxed text-gray-600 dark:text-zinc-400">{statusMsg || error || 'MONGODB_URI environment variable is not configured.'}</p>
            <p className="mt-4 text-xs leading-relaxed text-zinc-500">
              Set the <code className="rounded-md bg-gray-100 dark:bg-zinc-800/80 px-2 py-0.5 font-mono text-[11px] text-orange-400 ring-1 ring-white/10">MONGODB_URI</code> secret with your Atlas connection string.
            </p>
            <button
              type="button"
              onClick={loadStatus}
              className="mt-8 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-orange-600 to-orange-500 px-5 py-2.5 text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-orange-500/25 ring-1 ring-orange-400/30 transition-all hover:from-orange-500 hover:to-orange-400"
            >
              <RefreshCw className="h-4 w-4" /> Retry connection
            </button>
          </div>
        </div>
      </div>
    );
  }

  // --- Connected state ---
  const searchByCollection: Record<string, IndexInfo[]> = {};
  searchIndexes.forEach(idx => {
    const coll = idx.collection || 'unknown';
    if (!searchByCollection[coll]) searchByCollection[coll] = [];
    searchByCollection[coll].push(idx);
  });

  return (
    <div className="relative flex h-[calc(100vh-120px)] flex-col overflow-hidden bg-gradient-to-b from-white dark:from-zinc-950 via-gray-50 dark:via-zinc-950 to-gray-50 dark:to-black">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_70%_40%_at_80%_-10%,rgba(249,115,22,0.08),transparent)]" />

      {/* Toast notification */}
      {actionMsg && (
        <div className="fixed top-4 right-4 z-[60] max-w-md kb-slide-up">
          <div
            className={`flex items-start gap-3 rounded-xl border px-4 py-3 shadow-2xl shadow-black/30 ring-1 backdrop-blur-md ${
              actionMsg.type === 'success'
                ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300 ring-emerald-500/10'
                : 'border-red-500/25 bg-red-500/10 text-red-300 ring-red-500/10'
            }`}
          >
            {actionMsg.type === 'success' ? (
              <CheckCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            ) : (
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
            )}
            <span className="flex-1 text-sm leading-relaxed">{actionMsg.text}</span>
            <button type="button" onClick={() => setActionMsg(null)} className="flex-shrink-0 rounded-lg p-0.5 hover:bg-gray-100 dark:hover:bg-white/10">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="relative flex-shrink-0 overflow-hidden border-b border-gray-200 dark:border-white/[0.06] px-6 py-5 lg:px-8">
        <div className="pointer-events-none absolute -left-20 -top-16 h-56 w-56 rounded-full bg-orange-500/10 blur-3xl" />
        <div className="pointer-events-none absolute right-0 top-0 h-40 w-64 rounded-full bg-violet-500/10 blur-3xl" />
        <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-orange-500/30 to-amber-600/15 ring-1 ring-orange-500/25">
              <Database className="h-6 w-6 text-orange-400" />
            </div>
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-orange-400/90">Data layer</p>
              <h2 className="font-heading text-2xl font-bold tracking-tight text-gray-900 dark:text-white">Knowledge base</h2>
              <p className="mt-1 max-w-xl text-sm leading-relaxed text-gray-600 dark:text-zinc-400">
                MongoDB Atlas: databases, vector search indexes, document browse, and file ingestion for RAG.
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <div className="inline-flex items-center gap-2 rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 ring-1 ring-emerald-500/15">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-40" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
              </span>
              <span className="text-[11px] font-semibold text-emerald-300">Connected</span>
            </div>
            <button
              type="button"
              onClick={loadStatus}
              className="inline-flex items-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-3 py-2 text-sm font-medium text-gray-800 dark:text-zinc-200 ring-1 ring-white/[0.06] transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.08]"
              title="Refresh"
            >
              <RefreshCw className="h-4 w-4" />
              <span className="hidden sm:inline">Refresh</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main body: sidebar + content */}
      <div className="relative flex flex-1 min-h-0 overflow-hidden">
        {/* Database sidebar */}
        <aside className="flex w-[15rem] shrink-0 flex-col border-r border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-950/50 backdrop-blur-md ring-1 ring-white/[0.03]">
          <div className="border-b border-gray-200 dark:border-white/[0.06] p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">Databases</span>
              <span className="rounded-md bg-gray-100 dark:bg-zinc-800/80 px-1.5 py-0.5 font-mono text-[10px] text-gray-600 dark:text-zinc-400 ring-1 ring-white/[0.06]">
                {databases.length}
              </span>
            </div>
            <button
              type="button"
              onClick={() => {
                setShowCreateCollection(true);
                if (selectedDb) setNewDbName(selectedDb);
              }}
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-3 py-2.5 text-xs font-semibold text-gray-700 dark:text-zinc-300 ring-1 ring-white/[0.04] transition-all hover:border-orange-500/30 hover:bg-orange-500/10 hover:text-orange-200"
            >
              <Plus className="h-3.5 w-3.5" /> New collection
            </button>
          </div>

          <div className="flex-1 space-y-1 overflow-y-auto p-2">
            {databases.map(db => {
              const isActive = selectedDb === db.name;
              return (
                <button
                  type="button"
                  key={db.name}
                  onClick={() => selectDatabase(db.name)}
                  className={`group w-full rounded-xl border px-3 py-2.5 text-left transition-all duration-200 ${
                    isActive
                      ? 'border-orange-500/30 bg-orange-500/10 ring-1 ring-orange-500/20 shadow-lg shadow-orange-500/5'
                      : 'border-transparent hover:border-gray-300 dark:hover:border-white/[0.06] hover:bg-gray-100 dark:hover:bg-zinc-800/50'
                  }`}
                >
                  <div className="flex items-center gap-2.5">
                    <HardDrive
                      className={`h-4 w-4 shrink-0 ${isActive ? 'text-orange-400' : 'text-gray-400 dark:text-zinc-600 group-hover:text-zinc-400'}`}
                    />
                    <div className="min-w-0 flex-1">
                      <p
                        className={`truncate text-xs font-semibold ${isActive ? 'text-gray-900 dark:text-white' : 'text-gray-600 dark:text-zinc-400 group-hover:text-zinc-200'}`}
                      >
                        {db.name}
                      </p>
                      <p className={`mt-0.5 text-[10px] ${isActive ? 'text-orange-400/70' : 'text-gray-400 dark:text-zinc-600'}`}>
                        {db.collection_count} collection{db.collection_count !== 1 ? 's' : ''}
                      </p>
                    </div>
                    {isActive && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-orange-400/60" />}
                  </div>
                </button>
              );
            })}
          </div>
        </aside>

        {/* Main content */}
        <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-gray-50 dark:bg-zinc-950/30">
          {!selectedDb ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <div className="kb-fade-in max-w-sm text-center">
                <div className="relative mx-auto mb-6 flex h-20 w-20 items-center justify-center rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-900/50 ring-1 ring-white/[0.05]">
                  <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-violet-500/10 to-transparent" />
                  <Server className="relative h-9 w-9 text-zinc-500" />
                </div>
                <p className="text-sm font-medium text-gray-700 dark:text-zinc-300">Select a database</p>
                <p className="mt-2 text-xs leading-relaxed text-zinc-500">
                  Pick a database in the sidebar to browse collections, indexes, and documents.
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* Tab bar + action buttons */}
              <div className="flex shrink-0 flex-col gap-3 border-b border-gray-200 dark:border-white/[0.06] px-6 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex min-w-0 items-center gap-3">
                  {selectedColl ? (
                    <nav className="flex min-w-0 items-center gap-2 text-sm" aria-label="Breadcrumb">
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedColl(null);
                          setCollStats(null);
                          setCollIndexes([]);
                          setDocData(null);
                        }}
                        className="truncate font-medium text-zinc-500 transition-colors hover:text-orange-400"
                      >
                        {selectedDb}
                      </button>
                      <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-400 dark:text-zinc-600" />
                      <span className="truncate font-semibold text-gray-900 dark:text-white">{selectedColl}</span>
                    </nav>
                  ) : (
                    <div className="inline-flex rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-900/50 p-1 ring-1 ring-white/[0.04]">
                      <button
                        type="button"
                        onClick={() => setActiveTab('collections')}
                        className={`inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-semibold transition-all duration-200 ${
                          activeTab === 'collections'
                            ? 'bg-gradient-to-b from-orange-500/25 to-orange-600/15 text-orange-100 ring-1 ring-orange-500/30 shadow-md shadow-orange-500/10'
                            : 'text-gray-600 dark:text-zinc-400 hover:text-gray-800 dark:hover:text-zinc-200'
                        }`}
                      >
                        <Layers className="h-3.5 w-3.5" /> Collections
                      </button>
                      <button
                        type="button"
                        onClick={() => setActiveTab('indexes')}
                        className={`inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-semibold transition-all duration-200 ${
                          activeTab === 'indexes'
                            ? 'bg-gradient-to-b from-orange-500/25 to-orange-600/15 text-orange-100 ring-1 ring-orange-500/30 shadow-md shadow-orange-500/10'
                            : 'text-gray-600 dark:text-zinc-400 hover:text-gray-800 dark:hover:text-zinc-200'
                        }`}
                      >
                        <Search className="h-3.5 w-3.5" /> Indexes
                      </button>
                    </div>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {selectedDb && (
                    <button
                      type="button"
                      onClick={() => setShowUploadPanel(true)}
                      disabled={ingesting}
                      className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-xs font-semibold ring-1 transition-all ${
                        ingesting
                          ? 'cursor-not-allowed bg-gray-100 dark:bg-zinc-800 text-zinc-500 ring-white/[0.04]'
                          : 'bg-emerald-600/90 text-gray-900 dark:text-white shadow-lg shadow-emerald-500/20 ring-emerald-400/30 hover:bg-emerald-500'
                      }`}
                    >
                      {ingesting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                      Upload
                    </button>
                  )}
                  {activeTab === 'indexes' && !selectedColl && (
                    <button
                      type="button"
                      onClick={() => {
                        setShowCreateIndex(true);
                        setNewIndexCollection(collections.length > 0 ? collections[0].name : '');
                      }}
                      className="inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-orange-600 to-orange-500 px-3 py-2 text-xs font-semibold text-gray-900 dark:text-white shadow-lg shadow-orange-500/20 ring-1 ring-orange-400/25 transition-all hover:from-orange-500 hover:to-orange-400"
                    >
                      <Plus className="h-3.5 w-3.5" /> New index
                    </button>
                  )}
                </div>
              </div>

              {/* Scrollable content */}
              <div className="flex-1 space-y-6 overflow-y-auto p-6">

                {/* === COLLECTIONS TAB === */}
                {activeTab === 'collections' && !selectedColl && (
                  <div className="kb-fade-in">
                    {loadingCollections ? (
                      <div className="flex h-40 items-center justify-center gap-3">
                        <Loader2 className="h-5 w-5 animate-spin text-orange-400" />
                        <span className="text-sm text-gray-600 dark:text-zinc-400">Loading collections…</span>
                      </div>
                    ) : collections.length === 0 ? (
                      <div className="py-16 text-center">
                        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-900/60 ring-1 ring-white/[0.04]">
                          <FolderOpen className="h-8 w-8 text-zinc-500" />
                        </div>
                        <p className="text-sm font-medium text-gray-700 dark:text-zinc-300">No collections yet</p>
                        <p className="mx-auto mt-2 max-w-sm text-xs leading-relaxed text-zinc-500">
                          Create a collection or ingest files to populate this database.
                        </p>
                        <button
                          type="button"
                          onClick={() => {
                            setShowCreateCollection(true);
                            if (selectedDb) setNewDbName(selectedDb);
                          }}
                          className="mt-6 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-orange-600 to-orange-500 px-4 py-2.5 text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-orange-500/20 ring-1 ring-orange-400/25 transition-all hover:from-orange-500 hover:to-orange-400"
                        >
                          <Plus className="h-4 w-4" /> Create collection
                        </button>
                      </div>
                    ) : (
                      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                        {collections.map(coll => {
                          const collIdxCount = searchIndexes.filter(idx => idx.collection === coll.name).length;
                          const isRenaming = renamingColl === coll.name;
                          const isMenuOpen = collMenuOpen === coll.name;

                          return (
                            <div
                              key={coll.name}
                              role="button"
                              tabIndex={0}
                              onKeyDown={e => {
                                if (!isRenaming && (e.key === 'Enter' || e.key === ' ')) {
                                  e.preventDefault();
                                  selectCollection(coll.name);
                                }
                              }}
                              className="group relative cursor-pointer rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-900/40 p-5 ring-1 ring-white/[0.04] transition-all duration-300 hover:border-orange-500/20 hover:bg-gray-200 dark:hover:bg-zinc-900/70 hover:shadow-lg hover:shadow-orange-500/5"
                              onClick={() => !isRenaming && selectCollection(coll.name)}
                            >
                              <div className="mb-3 flex items-start justify-between">
                                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-sky-500/15 ring-1 ring-sky-500/25">
                                  <Layers className="h-5 w-5 text-sky-400" />
                                </div>
                                <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                                  <div className="relative">
                                    <button
                                      type="button"
                                      onClick={e => {
                                        e.stopPropagation();
                                        setCollMenuOpen(isMenuOpen ? null : coll.name);
                                      }}
                                      className="rounded-lg p-1.5 text-zinc-500 opacity-0 transition-all hover:bg-gray-100 dark:hover:bg-zinc-800 hover:text-gray-800 dark:hover:text-zinc-200 group-hover:opacity-100"
                                    >
                                      <MoreVertical className="h-4 w-4" />
                                    </button>
                                    {isMenuOpen && (
                                      <>
                                        <div className="fixed inset-0 z-10" onClick={() => setCollMenuOpen(null)} />
                                        <div className="absolute right-0 top-9 z-20 min-w-[140px] overflow-hidden rounded-xl border border-gray-200 dark:border-white/[0.08] bg-white dark:bg-zinc-900/95 py-1 shadow-2xl ring-1 ring-white/[0.06] backdrop-blur-md">
                                          <button
                                            type="button"
                                            onClick={e => {
                                              e.stopPropagation();
                                              setCollMenuOpen(null);
                                              setRenamingColl(coll.name);
                                              setRenameValue(coll.name);
                                            }}
                                            className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-gray-700 dark:text-zinc-300 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
                                          >
                                            <Pencil className="h-3.5 w-3.5" /> Rename
                                          </button>
                                          <button
                                            type="button"
                                            onClick={e => {
                                              e.stopPropagation();
                                              handleDeleteCollection(coll.name);
                                            }}
                                            className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-red-400 transition-colors hover:bg-red-500/10 hover:text-red-300"
                                          >
                                            <Trash2 className="h-3.5 w-3.5" /> Delete
                                          </button>
                                        </div>
                                      </>
                                    )}
                                  </div>
                                </div>
                              </div>

                              {isRenaming ? (
                                <div className="mb-2 flex items-center gap-2" onClick={e => e.stopPropagation()}>
                                  <input
                                    autoFocus
                                    value={renameValue}
                                    onChange={e => setRenameValue(e.target.value)}
                                    onKeyDown={e => {
                                      if (e.key === 'Enter') handleRenameCollection(coll.name);
                                      if (e.key === 'Escape') setRenamingColl(null);
                                    }}
                                    className="flex-1 rounded-lg border border-orange-500/40 bg-gray-100 dark:bg-zinc-800/80 px-2 py-1.5 text-sm text-gray-900 dark:text-white focus:border-orange-500 focus:outline-none focus:ring-1 focus:ring-orange-500/40"
                                  />
                                  <button
                                    type="button"
                                    onClick={() => handleRenameCollection(coll.name)}
                                    className="rounded-lg p-1.5 text-emerald-400 transition-colors hover:bg-emerald-500/10"
                                  >
                                    <Check className="h-4 w-4" />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setRenamingColl(null)}
                                    className="rounded-lg p-1.5 text-gray-600 dark:text-zinc-400 transition-colors hover:bg-gray-200 dark:hover:bg-zinc-700/60"
                                  >
                                    <X className="h-4 w-4" />
                                  </button>
                                </div>
                              ) : (
                                <h4 className="mb-1 truncate text-sm font-semibold text-gray-900 dark:text-white">{coll.name}</h4>
                              )}

                              <div className="mt-3 flex flex-wrap items-center gap-2">
                                <span className="rounded-md bg-gray-100 dark:bg-zinc-800/80 px-2 py-0.5 font-mono text-[11px] text-gray-600 dark:text-zinc-400 ring-1 ring-white/[0.05]">
                                  {coll.document_count.toLocaleString()} docs
                                </span>
                                <span className="rounded-md bg-gray-100 dark:bg-zinc-800/80 px-2 py-0.5 text-[11px] text-gray-600 dark:text-zinc-400 ring-1 ring-white/[0.05]">
                                  {coll.size_display}
                                </span>
                                {collIdxCount > 0 && (
                                  <span className="rounded-md bg-violet-500/15 px-2 py-0.5 text-[11px] font-medium text-violet-300 ring-1 ring-violet-500/25">
                                    {collIdxCount} idx
                                  </span>
                                )}
                              </div>

                              <ArrowRight className="absolute bottom-5 right-5 h-4 w-4 text-gray-400 dark:text-zinc-600 transition-colors group-hover:text-orange-400/80" />
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}

                {/* === COLLECTION DETAIL VIEW === */}
                {activeTab === 'collections' && selectedColl && (
                  <div className="kb-fade-in space-y-6">
                    {/* Stats row */}
                    {collStats && (
                      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                        <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-900/50 p-5 ring-1 ring-white/[0.04]">
                          <div className="flex items-start gap-3">
                            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-sky-500/15 ring-1 ring-sky-500/20">
                              <FileText className="h-5 w-5 text-sky-400" />
                            </div>
                            <div className="min-w-0">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Documents</p>
                              <p className="mt-1 text-2xl font-bold tabular-nums tracking-tight text-gray-900 dark:text-white">
                                {collStats.document_count.toLocaleString()}
                              </p>
                            </div>
                          </div>
                        </div>
                        <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-900/50 p-5 ring-1 ring-white/[0.04]">
                          <div className="flex items-start gap-3">
                            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 ring-1 ring-emerald-500/20">
                              <Upload className="h-5 w-5 text-emerald-400" />
                            </div>
                            <div className="min-w-0">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Files ingested</p>
                              <p className="mt-1 text-2xl font-bold tabular-nums tracking-tight text-gray-900 dark:text-white">{collStats.file_count}</p>
                            </div>
                          </div>
                        </div>
                        <div className="rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-900/50 p-5 ring-1 ring-white/[0.04]">
                          <div className="flex items-start gap-3">
                            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-500/20">
                              <Zap className="h-5 w-5 text-violet-400" />
                            </div>
                            <div className="min-w-0">
                              <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">Vector indexes</p>
                              <p className="mt-1 text-2xl font-bold tabular-nums tracking-tight text-gray-900 dark:text-white">
                                {collIndexes.filter(i => i.type === 'vectorSearch').length}
                              </p>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Ingested files */}
                    {collStats && collStats.files.length > 0 && (
                      <div className="rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gradient-to-br from-white dark:from-zinc-900/80 to-gray-50 dark:to-zinc-950/80 p-5 ring-1 ring-white/[0.05]">
                        <h4 className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-zinc-400">
                          <FileText className="h-3.5 w-3.5 text-emerald-400" /> Ingested files
                          <span className="font-normal normal-case tracking-normal text-gray-400 dark:text-zinc-600">({collStats.files.length})</span>
                        </h4>
                        <div className="space-y-1.5">
                          {collStats.files.map(fileName => (
                            <div
                              key={fileName}
                              className="group/file flex items-center justify-between rounded-lg border border-gray-200 dark:border-white/[0.05] bg-gray-50 dark:bg-zinc-900/40 px-3 py-2 transition-colors hover:border-gray-300 dark:hover:border-white/[0.1]"
                            >
                              <div className="flex min-w-0 items-center gap-2.5">
                                <FileText className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                                <span className="truncate text-sm text-gray-700 dark:text-zinc-300">{fileName}</span>
                              </div>
                              <button
                                type="button"
                                onClick={() => handleDeleteFile(fileName)}
                                className="rounded-lg p-1.5 text-zinc-500 opacity-0 transition-all hover:bg-red-500/10 hover:text-red-400 group-hover/file:opacity-100"
                                title="Delete file chunks"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Document browser */}
                    <div className="rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gradient-to-br from-white dark:from-zinc-900/90 via-gray-100 dark:via-zinc-900/70 to-gray-50 dark:to-zinc-950/90 p-5 shadow-xl shadow-black/20 ring-1 ring-white/[0.05]">
                      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                        <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-gray-600 dark:text-zinc-400">
                          <Eye className="h-3.5 w-3.5 text-sky-400" /> Documents
                          {docData && (
                            <span className="ml-1 font-normal normal-case tracking-normal text-gray-400 dark:text-zinc-600">
                              ({docData.total.toLocaleString()} total)
                            </span>
                          )}
                        </h4>
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="relative">
                            <input
                              value={docSearchInput}
                              onChange={e => setDocSearchInput(e.target.value)}
                              onKeyDown={e => e.key === 'Enter' && handleDocSearch()}
                              placeholder="Search documents…"
                              className="w-full min-w-[12rem] rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 py-2 pl-9 pr-3 text-xs text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-zinc-600 ring-1 ring-white/[0.04] transition-colors focus:border-orange-500/40 focus:outline-none focus:ring-1 focus:ring-orange-500/30 sm:w-52"
                            />
                            <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-500" />
                          </div>
                          <button
                            type="button"
                            onClick={handleDocSearch}
                            className="rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.06] px-3 py-2 text-xs font-semibold text-gray-800 dark:text-zinc-200 ring-1 ring-white/[0.05] transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.1]"
                          >
                            Search
                          </button>
                        </div>
                      </div>

                      {loadingDocs ? (
                        <div className="flex h-24 items-center justify-center gap-2">
                          <Loader2 className="h-4 w-4 animate-spin text-orange-400" />
                          <span className="text-xs text-zinc-500">Loading documents…</span>
                        </div>
                      ) : docData && docData.documents.length > 0 ? (
                        <div>
                          <div className="space-y-2 mb-4">
                            {docData.documents.map((doc, i) => {
                              const docId = doc._id || String(i);
                              const isExpanded = expandedDoc === docId;
                              const displayFields = Object.entries(doc).filter(([k]) => k !== '_id');
                              const previewText = doc.text || doc.content || '';
                              const previewSnippet = typeof previewText === 'string' ? previewText.slice(0, 120) : '';

                              const docTitle = doc.file_name || doc.name || doc.title || doc.source || null;
                              const hasBadges = docTitle || doc.chunk_id !== undefined || doc.section;

                              return (
                                <div
                                  key={docId}
                                  className={`overflow-hidden rounded-xl border transition-colors ${
                                    isExpanded
                                      ? 'border-gray-200 dark:border-white/[0.1] bg-gray-100 dark:bg-zinc-800/50'
                                      : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-900/30 hover:border-gray-300 dark:hover:border-white/[0.1]'
                                  }`}
                                >
                                  <button
                                    type="button"
                                    onClick={() => setExpandedDoc(isExpanded ? null : docId)}
                                    className="w-full px-4 py-3 text-left transition-colors"
                                  >
                                    <div className="flex items-start justify-between gap-3">
                                      <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                                          <span className="rounded-md bg-gray-100 dark:bg-zinc-800/80 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500 ring-1 ring-white/[0.05]">
                                            #{(docPage - 1) * 20 + i + 1}
                                          </span>
                                          {docTitle && (
                                            <span className="max-w-[250px] truncate rounded-md bg-sky-500/10 px-1.5 py-0.5 text-[10px] font-medium text-sky-400 ring-1 ring-sky-500/20">
                                              {docTitle}
                                            </span>
                                          )}
                                          {doc.chunk_id !== undefined && (
                                            <span className="rounded-md bg-gray-100 dark:bg-zinc-800/80 px-1.5 py-0.5 text-[10px] text-gray-600 dark:text-zinc-400 ring-1 ring-white/[0.05]">
                                              chunk {doc.chunk_id}
                                            </span>
                                          )}
                                          {doc.section && (
                                            <span className="max-w-[150px] truncate text-[10px] text-zinc-500">{doc.section}</span>
                                          )}
                                          {!hasBadges && (
                                            <span className="max-w-[200px] truncate rounded-md bg-gray-100 dark:bg-zinc-800/80 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500 ring-1 ring-white/[0.05]">
                                              {docId}
                                            </span>
                                          )}
                                        </div>
                                        {previewSnippet ? (
                                          <p className="truncate text-xs text-zinc-500">
                                            {previewSnippet}
                                            {typeof previewText === 'string' && previewText.length > 120 ? '…' : ''}
                                          </p>
                                        ) : (
                                          <p className="truncate text-xs text-gray-400 dark:text-zinc-600">
                                            {displayFields.slice(0, 3).map(([k]) => k).join(', ')}
                                            {displayFields.length > 3 ? ` +${displayFields.length - 3} more` : ''}
                                          </p>
                                        )}
                                      </div>
                                      <div className="mt-1 shrink-0">
                                        {isExpanded ? (
                                          <ChevronDown className="h-4 w-4 text-zinc-500" />
                                        ) : (
                                          <ChevronRight className="h-4 w-4 text-gray-400 dark:text-zinc-600" />
                                        )}
                                      </div>
                                    </div>
                                  </button>

                                  {isExpanded && (
                                    <div className="border-t border-gray-200 dark:border-white/[0.06] px-4 pb-4">
                                      <div className="mt-3 space-y-2">
                                        {displayFields.map(([key, value]) => {
                                          const isEmbedding = key === 'embedding' && value && typeof value === 'object' && 'dimensions' in value;
                                          const displayValue = isEmbedding
                                            ? `[${value.dimensions} dimensions] [${value.preview.map((v: number) => v.toFixed(6)).join(', ')}, ...]`
                                            : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
                                          return (
                                            <div key={key} className="flex gap-3">
                                              <span className="min-w-[100px] shrink-0 pt-0.5 font-mono text-[11px] font-medium text-orange-400/90">
                                                {key}
                                              </span>
                                              <div
                                                className={`max-h-48 flex-1 overflow-y-auto whitespace-pre-wrap break-all rounded-lg border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-950/60 p-2.5 text-xs ${
                                                  isEmbedding ? 'font-mono text-violet-300' : 'text-gray-700 dark:text-zinc-300'
                                                }`}
                                              >
                                                {displayValue}
                                              </div>
                                            </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>

                          {docData.total_pages > 1 && (
                            <div className="flex items-center justify-between border-t border-gray-200 dark:border-white/[0.06] pt-4">
                              <span className="text-xs tabular-nums text-zinc-500">
                                Page {docData.page} of {docData.total_pages}
                              </span>
                              <div className="flex items-center gap-2">
                                <button
                                  type="button"
                                  onClick={() => loadDocuments(docPage - 1, docSearch)}
                                  disabled={docPage <= 1}
                                  className="rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-zinc-300 ring-1 ring-white/[0.04] transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-30"
                                >
                                  Previous
                                </button>
                                <button
                                  type="button"
                                  onClick={() => loadDocuments(docPage + 1, docSearch)}
                                  disabled={docPage >= docData.total_pages}
                                  className="rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-zinc-300 ring-1 ring-white/[0.04] transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-30"
                                >
                                  Next
                                </button>
                              </div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="py-12 text-center">
                          <FolderOpen className="mx-auto mb-3 h-10 w-10 text-gray-400 dark:text-zinc-600" />
                          <p className="text-sm text-gray-600 dark:text-zinc-400">
                            {docSearch ? 'No documents match your search' : 'No documents in this collection'}
                          </p>
                          <p className="mt-2 text-xs text-gray-400 dark:text-zinc-600">
                            Upload PDF, DOCX, TXT, PPTX, XLSX, or HTML to get started.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* === INDEXES TAB === */}
                {activeTab === 'indexes' && !selectedColl && (
                  <div className="kb-fade-in space-y-6">
                    {loadingIndexes ? (
                      <div className="flex h-40 items-center justify-center gap-3">
                        <Loader2 className="h-5 w-5 animate-spin text-orange-400" />
                        <span className="text-sm text-gray-600 dark:text-zinc-400">Loading indexes…</span>
                      </div>
                    ) : searchIndexes.length === 0 ? (
                      <div className="py-16 text-center">
                        <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-900/60 ring-1 ring-white/[0.04]">
                          <Search className="h-8 w-8 text-zinc-500" />
                        </div>
                        <p className="text-sm font-medium text-gray-700 dark:text-zinc-300">No search indexes</p>
                        <p className="mx-auto mt-2 max-w-sm text-xs leading-relaxed text-zinc-500">
                          Add a vector search index to run semantic queries against your chunks.
                        </p>
                        <button
                          type="button"
                          onClick={() => {
                            setShowCreateIndex(true);
                            setNewIndexCollection(collections.length > 0 ? collections[0].name : '');
                          }}
                          className="mt-6 inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 px-4 py-2.5 text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-violet-500/20 ring-1 ring-violet-400/25 transition-all hover:from-violet-500 hover:to-purple-500"
                        >
                          <Plus className="h-4 w-4" /> Create vector index
                        </button>
                      </div>
                    ) : (
                      <div className="space-y-8">
                        {Object.entries(searchByCollection).map(([collName, idxList]) => (
                          <div key={collName}>
                            <div className="mb-4 flex items-center gap-3">
                              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-500/15 ring-1 ring-sky-500/20">
                                <Layers className="h-4 w-4 text-sky-400" />
                              </div>
                              <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-zinc-500">{collName}</span>
                              <div className="h-px flex-1 bg-gradient-to-r from-gray-100 dark:from-white/[0.08] to-transparent" />
                            </div>
                            <div className="space-y-3">
                              {idxList.map(idx => (
                                <div
                                  key={`${collName}-${idx.name}`}
                                  className="rounded-2xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-900/40 p-5 ring-1 ring-white/[0.04] transition-colors hover:border-violet-500/15"
                                >
                                  <div className="mb-3 flex items-start justify-between gap-3">
                                    <div className="flex min-w-0 items-center gap-3">
                                      <div
                                        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ring-1 ${
                                          idx.type === 'vectorSearch'
                                            ? 'bg-violet-500/15 ring-violet-500/25'
                                            : 'bg-sky-500/15 ring-sky-500/25'
                                        }`}
                                      >
                                        {idx.type === 'vectorSearch' ? (
                                          <Zap className="h-5 w-5 text-violet-400" />
                                        ) : (
                                          <Search className="h-5 w-5 text-sky-400" />
                                        )}
                                      </div>
                                      <div className="min-w-0">
                                        <p className="truncate text-sm font-semibold text-gray-900 dark:text-white">{idx.name}</p>
                                        <div className="mt-1 flex flex-wrap items-center gap-2">
                                          <span
                                            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                                              idx.type === 'vectorSearch'
                                                ? 'bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/20'
                                                : 'bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/20'
                                            }`}
                                          >
                                            {idx.type}
                                          </span>
                                          {idx.status && (
                                            <span
                                              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                                                idx.status === 'READY'
                                                  ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/20'
                                                  : 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/20'
                                              }`}
                                            >
                                              {idx.status}
                                            </span>
                                          )}
                                          {idx.queryable && (
                                            <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 ring-1 ring-emerald-500/15">
                                              queryable
                                            </span>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                    <div className="flex shrink-0 items-center gap-2">
                                      {idx.type === 'vectorSearch' && idx.queryable && (
                                        <button
                                          type="button"
                                          onClick={() => {
                                            setQueryIndex(
                                              queryIndex?.name === idx.name && queryIndex?.collection === collName ? null : idx
                                            );
                                            setQueryResults(null);
                                            setQueryText('');
                                          }}
                                          className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition-all ${
                                            queryIndex?.name === idx.name && queryIndex?.collection === collName
                                              ? 'border border-violet-500/35 bg-violet-500/20 text-violet-200 ring-1 ring-violet-500/25'
                                              : 'border border-gray-200 dark:border-white/[0.08] bg-gray-100 dark:bg-white/[0.04] text-gray-700 dark:text-zinc-300 ring-1 ring-white/[0.04] hover:bg-gray-100 dark:hover:bg-white/[0.08]'
                                          }`}
                                        >
                                          <Play className="h-3 w-3" /> Query
                                        </button>
                                      )}
                                      <button
                                        type="button"
                                        onClick={() => handleDeleteIndex(idx.name, collName)}
                                        className="rounded-lg p-1.5 text-zinc-500 transition-colors hover:bg-red-500/10 hover:text-red-400"
                                        title="Delete index"
                                      >
                                        <Trash2 className="h-3.5 w-3.5" />
                                      </button>
                                    </div>
                                  </div>

                                  {idx.fields && idx.fields.length > 0 && (
                                    <div className="mt-2 flex flex-wrap gap-2">
                                      {idx.fields.map((f, i) => (
                                        <div
                                          key={i}
                                          className="flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-950/50 px-3 py-1.5 text-[11px] ring-1 ring-white/[0.04]"
                                        >
                                          <span className="text-zinc-500">path</span>
                                          <span className="font-medium text-gray-800 dark:text-zinc-200">{f.path}</span>
                                          <span className="text-gray-300 dark:text-zinc-700">·</span>
                                          <span className="text-zinc-500">type</span>
                                          <span className={`font-semibold ${f.type === 'vector' ? 'text-violet-400' : 'text-sky-400'}`}>
                                            {f.type}
                                          </span>
                                          {f.numDimensions && (
                                            <>
                                              <span className="text-gray-300 dark:text-zinc-700">·</span>
                                              <span className="text-zinc-500">{f.numDimensions}d</span>
                                              {f.similarity && <span className="text-gray-400 dark:text-zinc-600">{f.similarity}</span>}
                                            </>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  )}

                                  {/* Vector search query panel */}
                                  {queryIndex?.name === idx.name && queryIndex?.collection === collName && (
                                    <div className="mt-4 border-t border-gray-200 dark:border-white/[0.06] pt-4">
                                      <div className="mb-3 flex items-center gap-2">
                                        <Zap className="h-4 w-4 text-violet-400" />
                                        <span className="text-sm font-semibold text-gray-900 dark:text-white">Vector search</span>
                                      </div>
                                      <div className="mb-3 flex flex-col gap-2 sm:flex-row">
                                        <input
                                          value={queryText}
                                          onChange={e => setQueryText(e.target.value)}
                                          onKeyDown={e => e.key === 'Enter' && handleVectorSearch()}
                                          placeholder="Describe what you are looking for…"
                                          className="min-w-0 flex-1 rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 px-3 py-2.5 text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-zinc-600 ring-1 ring-white/[0.04] focus:border-violet-500/40 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
                                        />
                                        <div className="flex gap-2">
                                          <select
                                            value={queryLimit}
                                            onChange={e => setQueryLimit(parseInt(e.target.value, 10))}
                                            className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 px-2 py-2.5 text-sm text-gray-900 dark:text-white ring-1 ring-white/[0.04] focus:border-violet-500/40 focus:outline-none sm:w-24"
                                          >
                                            <option value={5}>Top 5</option>
                                            <option value={10}>Top 10</option>
                                            <option value={20}>Top 20</option>
                                          </select>
                                          <button
                                            type="button"
                                            onClick={handleVectorSearch}
                                            disabled={queryLoading || !queryText.trim()}
                                            className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 px-4 py-2.5 text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-violet-500/20 ring-1 ring-violet-400/25 transition-all hover:from-violet-500 hover:to-purple-500 disabled:cursor-not-allowed disabled:from-zinc-800 disabled:to-zinc-800 disabled:text-zinc-600 disabled:shadow-none"
                                          >
                                            {queryLoading ? (
                                              <Loader2 className="h-4 w-4 animate-spin" />
                                            ) : (
                                              <Play className="h-4 w-4" />
                                            )}
                                            Search
                                          </button>
                                        </div>
                                      </div>

                                      {queryResults !== null && (
                                        <div className="mt-3 space-y-2">
                                          {queryResults.length === 0 ? (
                                            <p className="py-6 text-center text-sm text-zinc-500">No results found</p>
                                          ) : (
                                            queryResults.map((result, i) => {
                                              const resultId = result._id || String(i);
                                              const isExp = expandedResult === resultId;
                                              const score = result.score;
                                              const maxScore = queryResults[0]?.score || 1;
                                              const scorePercent = typeof score === 'number' ? Math.round((score / maxScore) * 100) : 0;
                                              const displayFields = Object.entries(result).filter(([k]) => k !== '_id' && k !== 'embedding' && k !== 'score');

                                              return (
                                                <div
                                                  key={resultId}
                                                  className={`overflow-hidden rounded-xl border transition-colors ${
                                                    isExp
                                                      ? 'border-violet-500/25 bg-violet-500/5'
                                                      : 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-900/30 hover:border-gray-300 dark:hover:border-white/[0.1]'
                                                  }`}
                                                >
                                                  <button
                                                    type="button"
                                                    onClick={() => setExpandedResult(isExp ? null : resultId)}
                                                    className="w-full px-4 py-3 text-left transition-colors"
                                                  >
                                                    <div className="flex items-center justify-between gap-3">
                                                      <div className="flex min-w-0 flex-1 items-center gap-3">
                                                        <span className="shrink-0 rounded-lg bg-violet-500/15 px-2 py-0.5 font-mono text-xs font-bold text-violet-300 ring-1 ring-violet-500/20">
                                                          #{i + 1}
                                                        </span>
                                                        {score !== undefined && (
                                                          <div className="flex shrink-0 items-center gap-2">
                                                            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-gray-100 dark:bg-zinc-800">
                                                              <div
                                                                className="h-full rounded-full bg-violet-500/70 transition-all"
                                                                style={{ width: `${scorePercent}%` }}
                                                              />
                                                            </div>
                                                            <span className="font-mono text-[10px] text-zinc-500">
                                                              {typeof score === 'number' ? score.toFixed(4) : score}
                                                            </span>
                                                          </div>
                                                        )}
                                                        {result.file_name && (
                                                          <span className="max-w-[150px] truncate rounded-md bg-sky-500/10 px-1.5 py-0.5 text-[10px] text-sky-400 ring-1 ring-sky-500/15">
                                                            {result.file_name}
                                                          </span>
                                                        )}
                                                        <p className="truncate text-xs text-zinc-500">
                                                          {(result.text || result.content || '').slice(0, 100)}
                                                        </p>
                                                      </div>
                                                      {isExp ? (
                                                        <ChevronDown className="h-4 w-4 shrink-0 text-zinc-500" />
                                                      ) : (
                                                        <ChevronRight className="h-4 w-4 shrink-0 text-gray-400 dark:text-zinc-600" />
                                                      )}
                                                    </div>
                                                  </button>
                                                  {isExp && (
                                                    <div className="border-t border-gray-200 dark:border-white/[0.06] px-4 pb-4">
                                                      <div className="mt-3 space-y-2">
                                                        {displayFields.map(([key, value]) => (
                                                          <div key={key} className="flex gap-3">
                                                            <span className="min-w-[100px] shrink-0 pt-0.5 font-mono text-[11px] font-medium text-violet-400/90">
                                                              {key}
                                                            </span>
                                                            <div className="max-h-48 flex-1 overflow-y-auto whitespace-pre-wrap break-all rounded-lg border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-950/60 p-2.5 text-xs text-gray-700 dark:text-zinc-300">
                                                              {typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)}
                                                            </div>
                                                          </div>
                                                        ))}
                                                      </div>
                                                    </div>
                                                  )}
                                                </div>
                                              );
                                            })
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Regular indexes */}
                    {regularIndexes.length > 0 && (
                      <div>
                        <button
                          type="button"
                          onClick={() => setShowRegularIndexes(!showRegularIndexes)}
                          className="mb-3 inline-flex items-center gap-2 rounded-lg px-1 py-1 text-xs font-medium text-zinc-500 transition-colors hover:text-gray-700 dark:hover:text-zinc-300"
                        >
                          {showRegularIndexes ? (
                            <ChevronDown className="h-3.5 w-3.5" />
                          ) : (
                            <ChevronRight className="h-3.5 w-3.5" />
                          )}
                          <Hash className="h-3 w-3" />
                          <span>Standard indexes ({regularIndexes.length})</span>
                        </button>

                        {showRegularIndexes && (
                          <div className="overflow-hidden rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-900/30 ring-1 ring-white/[0.04]">
                            <div className="divide-y divide-gray-200 dark:divide-white/[0.05]">
                              {regularIndexes.map((idx, i) => (
                                <div key={`regular-${i}`} className="flex items-center justify-between gap-3 px-4 py-3">
                                  <div className="flex min-w-0 items-center gap-3">
                                    <div className="h-1.5 w-1.5 shrink-0 rounded-full bg-gray-300 dark:bg-zinc-500" />
                                    <span className="truncate text-xs font-medium text-gray-800 dark:text-zinc-200">{idx.name}</span>
                                    <span className="shrink-0 text-[10px] text-gray-400 dark:text-zinc-600">{idx.collection}</span>
                                  </div>
                                  <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
                                    {idx.keys && (
                                      <span className="rounded-md bg-gray-100 dark:bg-zinc-800/80 px-2 py-0.5 font-mono text-[10px] text-zinc-500 ring-1 ring-white/[0.05]">
                                        {Object.entries(idx.keys)
                                          .map(([k, v]) => `${k}: ${v}`)
                                          .join(', ')}
                                      </span>
                                    )}
                                    {idx.unique && (
                                      <span className="rounded-md bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400 ring-1 ring-amber-500/20">
                                        unique
                                      </span>
                                    )}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </main>
      </div>

      {/* ==================== MODALS ==================== */}

      {/* Create Collection Modal */}
      <Modal open={showCreateCollection} onClose={() => { setShowCreateCollection(false); setNewDbName(''); setNewCollName(''); }} size="md">
        <div className="p-6">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-orange-500/15 ring-1 ring-orange-500/25">
              <Plus className="h-5 w-5 text-orange-400" />
            </div>
            <div>
              <h3 className="font-heading text-lg font-bold tracking-tight text-gray-900 dark:text-white">Create collection</h3>
              <p className="text-xs text-zinc-500">New database and collection pair</p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-600 dark:text-zinc-400">Database name</label>
              <input
                value={newDbName}
                onChange={e => setNewDbName(e.target.value)}
                placeholder="e.g. rag_knowledge_base"
                className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 px-3 py-2.5 text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-zinc-600 ring-1 ring-white/[0.04] transition-colors focus:border-orange-500/40 focus:outline-none focus:ring-1 focus:ring-orange-500/30"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-600 dark:text-zinc-400">Collection name</label>
              <input
                value={newCollName}
                onChange={e => setNewCollName(e.target.value)}
                placeholder="e.g. rag_documents"
                className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 px-3 py-2.5 text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-zinc-600 ring-1 ring-white/[0.04] transition-colors focus:border-orange-500/40 focus:outline-none focus:ring-1 focus:ring-orange-500/30"
              />
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-2 border-t border-gray-200 dark:border-white/[0.06] pt-4">
            <button
              type="button"
              onClick={() => {
                setShowCreateCollection(false);
                setNewDbName('');
                setNewCollName('');
              }}
              className="rounded-xl px-4 py-2 text-sm text-gray-600 dark:text-zinc-400 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreateCollection}
              disabled={creatingCollection || !newDbName.trim() || !newCollName.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-orange-600 to-orange-500 px-5 py-2 text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-orange-500/20 ring-1 ring-orange-400/25 transition-all hover:from-orange-500 hover:to-orange-400 disabled:cursor-not-allowed disabled:from-zinc-800 disabled:to-zinc-800 disabled:text-zinc-600 disabled:shadow-none"
            >
              {creatingCollection ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              Create
            </button>
          </div>
        </div>
      </Modal>

      {/* Create Index Modal */}
      <Modal open={showCreateIndex} onClose={() => setShowCreateIndex(false)} size="lg">
        <div className="p-6">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-500/15 ring-1 ring-violet-500/25">
              <Zap className="h-5 w-5 text-violet-400" />
            </div>
            <div>
              <h3 className="font-heading text-lg font-bold tracking-tight text-gray-900 dark:text-white">Vector search index</h3>
              <p className="text-xs text-zinc-500">Semantic search on embeddings</p>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-600 dark:text-zinc-400">Collection</label>
              <select
                value={newIndexCollection}
                onChange={e => setNewIndexCollection(e.target.value)}
                className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 px-3 py-2.5 text-sm text-gray-900 dark:text-white ring-1 ring-white/[0.04] focus:border-violet-500/40 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
              >
                {collections.map(c => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-600 dark:text-zinc-400">Index name</label>
              <input
                value={newIndexName}
                onChange={e => setNewIndexName(e.target.value)}
                className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 px-3 py-2.5 text-sm text-gray-900 dark:text-white ring-1 ring-white/[0.04] focus:border-violet-500/40 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-600 dark:text-zinc-400">Dimensions</label>
              <input
                type="number"
                value={newIndexDimensions}
                onChange={e => setNewIndexDimensions(parseInt(e.target.value, 10))}
                className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 px-3 py-2.5 text-sm text-gray-900 dark:text-white ring-1 ring-white/[0.04] focus:border-violet-500/40 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-600 dark:text-zinc-400">Similarity</label>
              <select
                value={newIndexSimilarity}
                onChange={e => setNewIndexSimilarity(e.target.value)}
                className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 px-3 py-2.5 text-sm text-gray-900 dark:text-white ring-1 ring-white/[0.04] focus:border-violet-500/40 focus:outline-none focus:ring-1 focus:ring-violet-500/30"
              >
                <option value="cosine">Cosine</option>
                <option value="dotProduct">Dot Product</option>
                <option value="euclidean">Euclidean</option>
              </select>
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-2 border-t border-gray-200 dark:border-white/[0.06] pt-4">
            <button
              type="button"
              onClick={() => setShowCreateIndex(false)}
              className="rounded-xl px-4 py-2 text-sm text-gray-600 dark:text-zinc-400 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreateIndex}
              disabled={creatingIndex || !newIndexName.trim() || !newIndexCollection}
              className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 px-5 py-2 text-sm font-semibold text-gray-900 dark:text-white shadow-lg shadow-violet-500/20 ring-1 ring-violet-400/25 transition-all hover:from-violet-500 hover:to-purple-500 disabled:cursor-not-allowed disabled:from-zinc-800 disabled:to-zinc-800 disabled:text-zinc-600 disabled:shadow-none"
            >
              {creatingIndex ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
              Create index
            </button>
          </div>
        </div>
      </Modal>

      {/* Upload File Modal */}
      <Modal open={showUploadPanel} onClose={() => !ingesting && setShowUploadPanel(false)} size="md">
        <div className="p-6">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-500/15 ring-1 ring-emerald-500/25">
              <CloudUpload className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <h3 className="font-heading text-lg font-bold tracking-tight text-gray-900 dark:text-white">Upload file</h3>
              <p className="text-xs text-zinc-500">Ingest into {selectedDb || 'database'}</p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-gray-600 dark:text-zinc-400">Project ID</label>
              <input
                type="text"
                value={ingestProjectId}
                onChange={e => setIngestProjectId(e.target.value)}
                placeholder="e.g. my_project"
                className="w-full rounded-xl border border-gray-200 dark:border-white/[0.08] bg-gray-50 dark:bg-zinc-950/50 px-3 py-2.5 text-sm text-gray-900 dark:text-white placeholder-gray-400 dark:placeholder-zinc-600 ring-1 ring-white/[0.04] transition-colors focus:border-emerald-500/40 focus:outline-none focus:ring-1 focus:ring-emerald-500/30"
              />
              <p className="mt-1.5 text-[10px] leading-relaxed text-gray-400 dark:text-zinc-600">
                Creates{' '}
                <code className="text-orange-400/80">knowledge_documents_{'{project_id}'}</code> +{' '}
                <code className="text-orange-400/80">knowledge_chunks_{'{project_id}'}</code>
              </p>
            </div>

            <div
              onDragOver={e => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={e => {
                e.preventDefault();
                setDragOver(false);
              }}
              onDrop={handleDrop}
              className={`relative rounded-2xl border-2 border-dashed transition-all duration-200 ${
                dragOver
                  ? 'border-emerald-500/50 bg-emerald-500/5'
                  : !ingestProjectId.trim()
                    ? 'border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-950/30'
                    : 'border-gray-200 dark:border-white/[0.12] bg-gray-50 dark:bg-zinc-900/40 hover:border-emerald-500/35 hover:bg-emerald-500/5'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileUpload}
                accept=".pdf,.doc,.docx,.txt,.pptx,.xlsx,.html,.htm,.csv"
                className="hidden"
                id="kb-file-upload-modal"
              />
              <label
                htmlFor={ingestProjectId.trim() ? 'kb-file-upload-modal' : undefined}
                className={`flex flex-col items-center px-4 py-8 ${ingestProjectId.trim() ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}`}
              >
                <CloudUpload
                  className={`mb-3 h-9 w-9 ${dragOver ? 'text-emerald-400' : 'text-zinc-500'} transition-colors`}
                />
                <p className="mb-1 text-sm text-gray-700 dark:text-zinc-300">
                  {dragOver ? 'Drop file here' : 'Drag and drop or click to browse'}
                </p>
                <p className="text-[10px] text-gray-400 dark:text-zinc-600">PDF, DOCX, PPTX, TXT, XLSX, HTML, CSV</p>
              </label>
            </div>

            {ingesting && ingestProgress && (
              <div className="flex items-center gap-3 rounded-xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-3 text-xs text-emerald-200 ring-1 ring-emerald-500/15">
                <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                <span className="leading-relaxed">{ingestProgress}</span>
              </div>
            )}

            <div className="flex items-start gap-2 rounded-xl border border-gray-200 dark:border-white/[0.06] bg-gray-50 dark:bg-zinc-950/40 px-3 py-2.5 text-[10px] leading-relaxed text-zinc-500 ring-1 ring-white/[0.04]">
              <Zap className="mt-0.5 h-3 w-3 shrink-0 text-gray-400 dark:text-zinc-600" />
              <p>
                Pipeline: parse → caption images (Gemini) → interleave → chunk (~500 chars) → keywords (TF) → embed
                (768d Vertex AI) → store
              </p>
            </div>
          </div>

          <div className="mt-5 flex justify-end gap-2 border-t border-gray-200 dark:border-white/[0.06] pt-4">
            <button
              type="button"
              onClick={() => !ingesting && setShowUploadPanel(false)}
              disabled={ingesting}
              className="rounded-xl px-4 py-2 text-sm text-gray-600 dark:text-zinc-400 transition-colors hover:bg-gray-100 dark:hover:bg-white/[0.06] hover:text-gray-900 dark:hover:text-white disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
