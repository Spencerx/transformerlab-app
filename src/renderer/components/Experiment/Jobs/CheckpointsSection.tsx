import React from 'react';
import { CheckpointsBody } from '../Tasks/ViewCheckpointsModal';

export default function CheckpointsSection({ jobId }: { jobId: string }) {
  return <CheckpointsBody jobId={jobId} onRestartSuccess={() => {}} />;
}
