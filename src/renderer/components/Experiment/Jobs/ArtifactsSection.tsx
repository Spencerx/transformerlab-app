import React from 'react';
import { JobArtifactsBody } from '../Tasks/JobArtifacts/JobArtifactsModal';

export default function ArtifactsSection({ jobId }: { jobId: string }) {
  return <JobArtifactsBody jobId={jobId} showTitle={false} />;
}
