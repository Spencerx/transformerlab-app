import { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  CircularProgress,
  Sheet,
  Stack,
  Button,
  IconButton,
} from '@mui/joy';
import { Download, X } from 'lucide-react';
import { getAPIFullPath } from 'renderer/lib/transformerlab-api-sdk';
import { useExperimentInfo } from 'renderer/lib/ExperimentInfoContext';
import { fetchWithAuth } from 'renderer/lib/authContext';
import Model3DViewer from 'renderer/components/Shared/Model3DViewer';

export interface PreviewableItem {
  filename: string;
  jobId: string;
}

interface ArtifactPreviewPaneProps {
  item: PreviewableItem | null;
  onClose: () => void;
}

const PREVIEWABLE_EXTENSIONS = [
  'json',
  'txt',
  'log',
  'png',
  'jpg',
  'jpeg',
  'gif',
  'bmp',
  'webp',
  'svg',
  'mp4',
  'webm',
  'mov',
  'mp3',
  'wav',
  'ogg',
  'm4a',
  'flac',
  'glb',
  'gltf',
];

export function canPreviewFile(filename: string): boolean {
  const ext = filename.toLowerCase().split('.').pop() || '';
  return PREVIEWABLE_EXTENSIONS.includes(ext);
}

export default function ArtifactPreviewPane({
  item,
  onClose,
}: ArtifactPreviewPaneProps) {
  const { experimentInfo } = useExperimentInfo();
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState<any>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Cleanup blob URLs when component unmounts or preview changes
  useEffect(() => {
    return () => {
      if (previewData?.url && previewData.url.startsWith('blob:')) {
        URL.revokeObjectURL(previewData.url);
      }
    };
  }, [previewData]);

  // Load preview when item changes
  useEffect(() => {
    if (!item) {
      setPreviewData(null);
      setPreviewError(null);
      return;
    }
    loadPreview(item);
  }, [item?.filename, item?.jobId]);

  const getFileExtension = (filename: string) => {
    return filename.toLowerCase().split('.').pop() || '';
  };

  const loadPreview = async (previewItem: PreviewableItem) => {
    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewData(null);

    const ext = getFileExtension(previewItem.filename);

    try {
      if (ext === 'json') {
        const url = getAPIFullPath('jobs', ['getArtifact'], {
          experimentId: experimentInfo?.id,
          jobId: previewItem.jobId,
          filename: previewItem.filename,
        });
        const response = await fetchWithAuth(`${url}?task=view`);
        if (!response.ok) throw new Error('Failed to load artifact');
        const jsonData = await response.json();
        setPreviewData({ type: 'json', data: jsonData });
      } else if (['txt', 'log'].includes(ext)) {
        const url = getAPIFullPath('jobs', ['getArtifact'], {
          experimentId: experimentInfo?.id,
          jobId: previewItem.jobId,
          filename: previewItem.filename,
        });
        const response = await fetchWithAuth(`${url}?task=view`);
        if (!response.ok) throw new Error('Failed to load artifact');
        const textData = await response.text();
        setPreviewData({ type: 'text', data: textData });
      } else if (
        ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg'].includes(ext)
      ) {
        const imageUrl = getAPIFullPath('jobs', ['getArtifact'], {
          experimentId: experimentInfo?.id,
          jobId: previewItem.jobId,
          filename: previewItem.filename,
        });
        setPreviewData({ type: 'image', url: `${imageUrl}?task=view` });
      } else if (['mp4', 'webm', 'mov'].includes(ext)) {
        const videoUrl = getAPIFullPath('jobs', ['getArtifact'], {
          experimentId: experimentInfo?.id,
          jobId: previewItem.jobId,
          filename: previewItem.filename,
        });
        setPreviewData({ type: 'video', url: `${videoUrl}?task=view` });
      } else if (['mp3', 'wav', 'ogg', 'm4a', 'flac'].includes(ext)) {
        const audioUrl = getAPIFullPath('jobs', ['getArtifact'], {
          experimentId: experimentInfo?.id,
          jobId: previewItem.jobId,
          filename: previewItem.filename,
        });
        setPreviewData({ type: 'audio', url: `${audioUrl}?task=view` });
      } else if (['glb', 'gltf'].includes(ext)) {
        const modelUrl = getAPIFullPath('jobs', ['getArtifact'], {
          experimentId: experimentInfo?.id,
          jobId: previewItem.jobId,
          filename: previewItem.filename,
        });
        setPreviewData({
          type: 'model3d',
          url: `${modelUrl}?task=view`,
          filename: previewItem.filename,
        });
      }
    } catch {
      setPreviewError('Failed to load artifact preview');
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleDownload = async () => {
    if (!item) return;
    try {
      const downloadUrl = getAPIFullPath('jobs', ['getArtifact'], {
        experimentId: experimentInfo?.id,
        jobId: item.jobId,
        filename: item.filename,
      });
      const response = await fetchWithAuth(`${downloadUrl}?task=download`);
      if (!response.ok) throw new Error('Failed to download artifact');
      const blob = await response.blob();
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = item.filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      setTimeout(() => URL.revokeObjectURL(blobUrl), 100);
    } catch (error) {
      console.error('Download failed:', error);
    }
  };

  const renderPreview = () => {
    if (previewLoading) {
      return (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
          <CircularProgress />
        </Box>
      );
    }

    if (previewError) {
      return (
        <Box sx={{ p: 3, textAlign: 'center' }}>
          <Typography color="danger">{previewError}</Typography>
        </Box>
      );
    }

    if (!previewData) {
      return null;
    }

    const preStyle = {
      margin: 0,
      fontFamily: 'monospace',
      fontSize: '12px',
      whiteSpace: 'pre-wrap' as const,
      wordBreak: 'break-word' as const,
    };

    switch (previewData.type) {
      case 'json':
        return (
          <Box
            sx={{
              p: 2,
              overflow: 'auto',
              flex: 1,
              backgroundColor: 'background.level1',
              borderRadius: 'sm',
            }}
          >
            <pre style={preStyle}>
              {JSON.stringify(previewData.data, null, 2)}
            </pre>
          </Box>
        );
      case 'text':
        return (
          <Box
            sx={{
              p: 2,
              overflow: 'auto',
              flex: 1,
              backgroundColor: 'background.level1',
              borderRadius: 'sm',
            }}
          >
            <pre style={preStyle}>{previewData.data}</pre>
          </Box>
        );
      case 'image':
        return (
          <Box
            sx={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              overflow: 'auto',
              flex: 1,
              p: 2,
            }}
          >
            <img
              src={previewData.url}
              alt={item?.filename}
              style={{
                maxWidth: '100%',
                maxHeight: '100%',
                objectFit: 'contain',
              }}
            />
          </Box>
        );
      case 'video':
        return (
          <Box
            sx={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              overflow: 'auto',
              flex: 1,
              p: 2,
            }}
          >
            {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
            <video controls style={{ maxWidth: '100%', maxHeight: '100%' }}>
              <source src={previewData.url} />
              Your browser does not support the video tag.
            </video>
          </Box>
        );
      case 'audio':
        return (
          <Box
            sx={{
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              overflow: 'auto',
              flex: 1,
              p: 2,
            }}
          >
            <audio controls style={{ width: '100%' }}>
              <source src={previewData.url} />
              Your browser does not support the audio element.
            </audio>
          </Box>
        );
      case 'model3d':
        return (
          <Box sx={{ flex: 1, overflow: 'hidden' }}>
            <Model3DViewer
              modelUrl={previewData.url}
              filename={previewData.filename}
            />
          </Box>
        );
      default:
        return null;
    }
  };

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}
    >
      {item ? (
        <>
          <Stack
            direction="row"
            justifyContent="space-between"
            alignItems="center"
            sx={{ mb: 1, flexShrink: 0 }}
          >
            <Typography level="title-md" noWrap sx={{ flex: 1 }}>
              {item.filename}
            </Typography>
            <Stack direction="row" spacing={1} sx={{ flexShrink: 0 }}>
              <Button
                size="sm"
                variant="outlined"
                startDecorator={<Download size={16} />}
                onClick={handleDownload}
              >
                Download
              </Button>
              <IconButton size="sm" variant="plain" onClick={onClose}>
                <X size={16} />
              </IconButton>
            </Stack>
          </Stack>
          <Sheet
            sx={{
              flex: 1,
              overflow: 'auto',
              borderRadius: 'sm',
              border: '1px solid',
              borderColor: 'divider',
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            {renderPreview()}
          </Sheet>
        </>
      ) : (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
          }}
        >
          <Typography level="body-md" color="neutral">
            Select an artifact to preview
          </Typography>
        </Box>
      )}
    </Box>
  );
}
