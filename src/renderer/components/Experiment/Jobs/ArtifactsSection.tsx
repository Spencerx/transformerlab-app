import React from 'react';
import Box from '@mui/joy/Box';
import Typography from '@mui/joy/Typography';
import CircularProgress from '@mui/joy/CircularProgress';
import Button from '@mui/joy/Button';
import { DownloadIcon } from 'lucide-react';
import { useSWRWithAuth, useAuth } from 'renderer/lib/authContext';
import { useExperimentInfo } from 'renderer/lib/ExperimentInfoContext';
import * as chatAPI from 'renderer/lib/transformerlab-api-sdk';

export default function ArtifactsSection({ jobId }: { jobId: string }) {
  const { experimentInfo } = useExperimentInfo();
  const { fetchWithAuth } = useAuth();

  const { data, isLoading } = useSWRWithAuth(
    experimentInfo?.id && jobId
      ? `${chatAPI.API_URL()}experiment/${experimentInfo.id}/jobs/${jobId}/artifacts`
      : null,
  );

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', pt: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  const artifacts: { filename: string; size?: number }[] =
    data?.artifacts ?? [];

  if (artifacts.length === 0) {
    return <Typography level="body-sm">No artifacts available.</Typography>;
  }

  async function downloadArtifact(filename: string) {
    if (!experimentInfo?.id) return;
    const url = `${chatAPI.API_URL()}experiment/${experimentInfo.id}/jobs/${jobId}/artifact/${filename}`;
    try {
      const res = await fetchWithAuth(url);
      if (!res.ok) {
        console.error(`Failed to download artifact: HTTP ${res.status}`);
        return;
      }
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
    } catch (err) {
      console.error('Failed to download artifact:', err);
    }
  }

  return (
    <Box>
      <Typography level="title-md" sx={{ mb: 2 }}>
        Artifacts
      </Typography>
      {artifacts.map((artifact) => (
        <Box
          key={artifact.filename}
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            py: 1,
            borderBottom: '1px solid',
            borderColor: 'divider',
          }}
        >
          <Typography level="body-sm" sx={{ fontFamily: 'monospace' }}>
            {artifact.filename}
          </Typography>
          <Button
            size="sm"
            variant="plain"
            startDecorator={<DownloadIcon size={14} />}
            onClick={() => downloadArtifact(artifact.filename)}
          >
            Download
          </Button>
        </Box>
      ))}
    </Box>
  );
}
