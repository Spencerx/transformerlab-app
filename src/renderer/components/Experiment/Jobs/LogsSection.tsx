import React from 'react';
import EmbeddableStreamingOutput from '../Tasks/EmbeddableStreamingOutput';

export default function LogsSection({
  jobId,
  jobStatus,
}: {
  jobId: string;
  jobStatus: string;
}) {
  return (
    <EmbeddableStreamingOutput
      jobId={jobId}
      jobStatus={jobStatus}
      tabs={['output', 'provider']}
    />
  );
}
