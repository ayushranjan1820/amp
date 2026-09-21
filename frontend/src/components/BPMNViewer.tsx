import { useEffect, useRef, useState, useCallback } from 'react';
import { ZoomIn, ZoomOut, Maximize2, Minimize2, Download, Save, RotateCcw } from 'lucide-react';
import 'bpmn-js/dist/assets/diagram-js.css';
import 'bpmn-js/dist/assets/bpmn-font/css/bpmn.css';
import 'bpmn-js/dist/assets/bpmn-js.css';

interface BPMNViewerProps {
  xml: string;
  onXmlChange?: (newXml: string) => void;
}

export default function BPMNViewer({ xml, onXmlChange }: BPMNViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const modelerRef = useRef<any>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const originalXmlRef = useRef<string>(xml);

  const initModeler = useCallback(async () => {
    if (!containerRef.current || !xml) return;

    try {
      setIsLoading(true);
      setError(null);

      const BpmnModeler = (await import('bpmn-js/lib/Modeler')).default;
      
      if (modelerRef.current) {
        modelerRef.current.destroy();
      }

      modelerRef.current = new BpmnModeler({
        container: containerRef.current,
        keyboard: {
          bindTo: document,
        },
      });

      modelerRef.current.on('commandStack.changed', () => {
        setHasChanges(true);
      });

      await modelerRef.current.importXML(xml);
      originalXmlRef.current = xml;
      
      const canvas = modelerRef.current.get('canvas');
      canvas.zoom('fit-viewport');
      
      setIsLoading(false);
      setHasChanges(false);
    } catch (err: any) {
      console.error('BPMN rendering error:', err);
      setError(err.message || 'Failed to render BPMN diagram');
      setIsLoading(false);
    }
  }, [xml]);

  useEffect(() => {
    initModeler();

    return () => {
      if (modelerRef.current) {
        modelerRef.current.destroy();
        modelerRef.current = null;
      }
    };
  }, [initModeler]);

  const handleZoomIn = () => {
    if (modelerRef.current) {
      const canvas = modelerRef.current.get('canvas');
      canvas.zoom(canvas.zoom() * 1.2);
    }
  };

  const handleZoomOut = () => {
    if (modelerRef.current) {
      const canvas = modelerRef.current.get('canvas');
      canvas.zoom(canvas.zoom() / 1.2);
    }
  };

  const handleFitToViewport = () => {
    if (modelerRef.current) {
      const canvas = modelerRef.current.get('canvas');
      canvas.zoom('fit-viewport');
    }
  };

  const handleSaveXML = async () => {
    if (modelerRef.current) {
      try {
        const { xml: newXml } = await modelerRef.current.saveXML({ format: true });
        if (onXmlChange) {
          onXmlChange(newXml);
        }
        originalXmlRef.current = newXml;
        setHasChanges(false);
        
        const blob = new Blob([newXml], { type: 'application/xml' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'bpmn-diagram.bpmn';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        console.error('Failed to save XML:', err);
      }
    }
  };

  const handleReset = async () => {
    if (modelerRef.current && originalXmlRef.current) {
      try {
        await modelerRef.current.importXML(originalXmlRef.current);
        const canvas = modelerRef.current.get('canvas');
        canvas.zoom('fit-viewport');
        setHasChanges(false);
      } catch (err) {
        console.error('Failed to reset diagram:', err);
      }
    }
  };

  const handleDownloadSVG = async () => {
    if (modelerRef.current) {
      try {
        const { svg } = await modelerRef.current.saveSVG();
        const blob = new Blob([svg], { type: 'image/svg+xml' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'bpmn-diagram.svg';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (err) {
        console.error('Failed to export SVG:', err);
      }
    }
  };

  const toggleFullscreen = useCallback(() => {
    if (!wrapperRef.current) return;
    if (!document.fullscreenElement) {
      wrapperRef.current.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }, []);

  useEffect(() => {
    const handler = () => {
      setIsFullscreen(!!document.fullscreenElement);
      setTimeout(() => {
        if (modelerRef.current) {
          const canvas = modelerRef.current.get('canvas');
          canvas.zoom('fit-viewport');
        }
      }, 100);
    };
    document.addEventListener('fullscreenchange', handler);
    return () => document.removeEventListener('fullscreenchange', handler);
  }, []);

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 mt-4">
        <p className="text-red-600 dark:text-red-400 text-sm">
          Failed to render BPMN diagram: {error}
        </p>
        <details className="mt-2">
          <summary className="text-xs text-red-500 cursor-pointer">View raw XML</summary>
          <pre className="mt-2 text-xs bg-gray-100 dark:bg-gray-800 p-2 rounded overflow-auto max-h-40">
            {xml}
          </pre>
        </details>
      </div>
    );
  }

  return (
    <div ref={wrapperRef} className={`mt-4 ${isFullscreen ? 'bg-white dark:bg-gray-900 p-4 h-screen flex flex-col' : ''}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-semibold text-gray-700 dark:text-gray-300">
            BPMN Diagram
          </h4>
          <span className="text-xs text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded">
            Editable
          </span>
          {hasChanges && (
            <span className="text-xs text-orange-500 bg-orange-100 dark:bg-orange-900/30 px-2 py-0.5 rounded">
              Unsaved changes
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {hasChanges && (
            <button
              onClick={handleReset}
              className="p-1.5 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors"
              title="Reset to original"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={handleZoomOut}
            className="p-1.5 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors"
            title="Zoom out"
          >
            <ZoomOut className="w-4 h-4" />
          </button>
          <button
            onClick={handleZoomIn}
            className="p-1.5 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors"
            title="Zoom in"
          >
            <ZoomIn className="w-4 h-4" />
          </button>
          <button
            onClick={handleFitToViewport}
            className="p-1.5 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors"
            title="Fit to viewport"
          >
            <Maximize2 className="w-4 h-4" />
          </button>
          <button
            onClick={handleDownloadSVG}
            className="p-1.5 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors"
            title="Download as SVG"
          >
            <Download className="w-4 h-4" />
          </button>
          <button
            onClick={handleSaveXML}
            className="p-1.5 text-gray-500 hover:text-orange-600 dark:hover:text-orange-400 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors"
            title="Save BPMN file"
          >
            <Save className="w-4 h-4" />
          </button>
          <button
            onClick={toggleFullscreen}
            className="p-1.5 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors"
            title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          >
            {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
        </div>
      </div>
      <div className="text-xs text-gray-500 dark:text-gray-400 mb-2">
        Click and drag elements to move them. Use the context menu (right-click) to add or delete elements.
      </div>
      <div 
        ref={containerRef}
        className={`bg-white border border-gray-200 dark:border-gray-700 rounded-lg ${
          isFullscreen ? 'flex-1' : 'h-[450px]'
        }`}
        style={{ minHeight: isFullscreen ? undefined : '450px' }}
      >
        {isLoading && (
          <div className="flex items-center justify-center h-full">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
            <span className="ml-2 text-gray-500">Loading diagram...</span>
          </div>
        )}
      </div>
    </div>
  );
}
