import { useState } from 'react';
import { Upload, FileText, Download } from 'lucide-react';

export function UploadSection() {
  const [file, setFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      setFile(droppedFile);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
    }
  };

  const handleProcess = () => {
    if (!file) return;
    
    setIsProcessing(true);
    // Simulate processing
    setTimeout(() => {
      setIsProcessing(false);
      // In a real app, this would trigger the download
      alert('Calendar file would be downloaded here');
    }, 2000);
  };

  return (
    <section id="upload-section" className="border-t border-zinc-800 px-6 py-24">
      <div className="mx-auto max-w-2xl">
        <h2 className="mb-12 text-center text-4xl">Upload Your Course Outline</h2>
        
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`mb-6 rounded-lg border-2 border-dashed p-12 text-center transition-colors ${
            isDragging
              ? 'border-blue-500 bg-blue-500/10'
              : 'border-zinc-700 bg-zinc-900/50'
          }`}
        >
          <input
            type="file"
            id="file-upload"
            className="hidden"
            accept=".pdf,.doc,.docx,.txt"
            onChange={handleFileInput}
          />
          
          {!file ? (
            <>
              <Upload className="mx-auto mb-4 h-12 w-12 text-zinc-600" />
              <p className="mb-2 text-zinc-300">
                Drag and drop your course outline here
              </p>
              <p className="mb-4 text-sm text-zinc-500">or</p>
              <label
                htmlFor="file-upload"
                className="inline-block cursor-pointer rounded-lg border border-blue-500/20 bg-blue-500/10 px-6 py-3 transition-colors hover:bg-blue-500/20"
              >
                Browse Files
              </label>
              <p className="mt-4 text-sm text-zinc-500">
                Supports PDF, DOCX, and TXT files
              </p>
            </>
          ) : (
            <div className="flex items-center justify-center gap-3">
              <FileText className="h-8 w-8 text-blue-400" />
              <div className="text-left">
                <p className="text-zinc-300">{file.name}</p>
                <p className="text-sm text-zinc-500">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
              </div>
            </div>
          )}
        </div>

        {file && (
          <div className="flex gap-4">
            <button
              onClick={() => setFile(null)}
              className="flex-1 rounded-lg border border-zinc-700 px-6 py-3 transition-colors hover:bg-zinc-800"
            >
              Remove File
            </button>
            <button
              onClick={handleProcess}
              disabled={isProcessing}
              className="flex-1 inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-6 py-3 transition-colors hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Download className="h-5 w-5" />
              {isProcessing ? 'Processing...' : 'Generate Calendar'}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
