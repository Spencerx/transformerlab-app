import React from 'react';
import Box from '@mui/joy/Box';
import Typography from '@mui/joy/Typography';
import Divider from '@mui/joy/Divider';
import CircularProgress from '@mui/joy/CircularProgress';
import { JobRecord } from './jobDetailUtils';

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Box sx={{ display: 'flex', gap: 2, py: 0.75 }}>
      <Typography
        level="body-sm"
        sx={{ width: 160, flexShrink: 0, color: 'text.secondary' }}
      >
        {label}
      </Typography>
      <Typography level="body-sm">{value ?? '—'}</Typography>
    </Box>
  );
}

export default function OverviewSection({ job }: { job: JobRecord | null }) {
  if (!job) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', pt: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  const d = job.job_data ?? {};
  const createdAt = job.created_at
    ? new Date(job.created_at).toLocaleString()
    : null;

  return (
    <Box sx={{ maxWidth: 600 }}>
      <Typography level="title-md" sx={{ mb: 1 }}>
        Job Details
      </Typography>
      <Divider sx={{ mb: 2 }} />
      <Row label="Job ID" value={job.id} />
      <Row label="Status" value={job.status} />
      <Row label="Type" value={job.type} />
      <Row label="Created" value={createdAt} />
      {d.provider_name && (
        <Row label="Provider" value={String(d.provider_name)} />
      )}
      {d.cluster_name && <Row label="Cluster" value={String(d.cluster_name)} />}
      {typeof d.description === 'string' && d.description.trim() && (
        <Box sx={{ py: 0.75 }}>
          <Typography
            level="body-sm"
            sx={{ width: 160, color: 'text.secondary', mb: 0.5 }}
          >
            Description
          </Typography>
          <Typography
            level="body-sm"
            sx={{
              whiteSpace: 'pre-wrap',
              background: 'var(--joy-palette-background-surface)',
              p: 1.5,
              borderRadius: 'sm',
            }}
          >
            {String(d.description)}
          </Typography>
        </Box>
      )}
      {(d as any).template_name && (
        <Row label="Template" value={String((d as any).template_name)} />
      )}
      {typeof job.progress === 'number' && (
        <Row label="Progress" value={`${job.progress}%`} />
      )}
      {d.error_msg && (
        <>
          <Divider sx={{ my: 2 }} />
          <Typography level="title-sm" color="danger" sx={{ mb: 1 }}>
            Error
          </Typography>
          <Typography
            level="body-sm"
            sx={{
              fontFamily: 'monospace',
              whiteSpace: 'pre-wrap',
              background: 'var(--joy-palette-background-surface)',
              p: 1.5,
              borderRadius: 'sm',
            }}
          >
            {String(d.error_msg)}
          </Typography>
        </>
      )}
    </Box>
  );
}
