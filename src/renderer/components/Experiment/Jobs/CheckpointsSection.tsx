import React from 'react';
import Box from '@mui/joy/Box';
import Typography from '@mui/joy/Typography';
import CircularProgress from '@mui/joy/CircularProgress';
import { useSWRWithAuth } from 'renderer/lib/authContext';
import { useExperimentInfo } from 'renderer/lib/ExperimentInfoContext';
import * as chatAPI from 'renderer/lib/transformerlab-api-sdk';
import { formatBytes } from 'renderer/lib/utils';

export default function CheckpointsSection({ jobId }: { jobId: string }) {
  const { experimentInfo } = useExperimentInfo();

  const { data, isLoading } = useSWRWithAuth(
    experimentInfo?.id && jobId
      ? `${chatAPI.API_URL()}experiment/${experimentInfo.id}/jobs/${jobId}/checkpoints`
      : null,
  );

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', pt: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  const checkpoints: { filename: string; date?: string; size?: number }[] =
    data?.checkpoints ?? [];

  if (checkpoints.length === 0) {
    return <Typography level="body-sm">No checkpoints available.</Typography>;
  }

  return (
    <Box>
      <Typography level="title-md" sx={{ mb: 2 }}>
        Checkpoints
      </Typography>
      {checkpoints.map((ckpt) => (
        <Box
          key={ckpt.filename}
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
            {ckpt.filename}
          </Typography>
          <Box sx={{ display: 'flex', gap: 2 }}>
            {ckpt.size != null && (
              <Typography level="body-xs" color="neutral">
                {formatBytes(ckpt.size)}
              </Typography>
            )}
            {ckpt.date && (
              <Typography level="body-xs" color="neutral">
                {new Date(ckpt.date).toLocaleString()}
              </Typography>
            )}
          </Box>
        </Box>
      ))}
    </Box>
  );
}
