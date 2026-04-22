import React from 'react';
import Typography from '@mui/joy/Typography';
import { EvalResultsBody } from '../Tasks/ViewEvalResultsModal';

export default function EvalResultsSection({
  jobId,
  evalFiles,
}: {
  jobId: string;
  evalFiles: string[];
}) {
  if (evalFiles.length === 0) {
    return <Typography level="body-sm">No eval results available.</Typography>;
  }

  return <EvalResultsBody jobId={jobId} enabled />;
}
