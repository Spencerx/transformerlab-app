import React from 'react';
import { SweepResultsBody } from '../Tasks/ViewSweepResultsModal';

export default function SweepResultsSection({ jobId }: { jobId: string }) {
  return <SweepResultsBody jobId={jobId} />;
}
