import React, { useState } from 'react';
import Box from '@mui/joy/Box';
import Typography from '@mui/joy/Typography';
import CircularProgress from '@mui/joy/CircularProgress';
import Select from '@mui/joy/Select';
import Option from '@mui/joy/Option';
import Table from '@mui/joy/Table';
import { useSWRWithAuth } from 'renderer/lib/authContext';
import { useExperimentInfo } from 'renderer/lib/ExperimentInfoContext';
import * as chatAPI from 'renderer/lib/transformerlab-api-sdk';

export default function EvalResultsSection({
  jobId,
  evalFiles,
}: {
  jobId: string;
  evalFiles: string[];
}) {
  const { experimentInfo } = useExperimentInfo();
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);

  const { data: reportData, isLoading: reportLoading } = useSWRWithAuth(
    experimentInfo?.id && evalFiles.length > 0
      ? chatAPI.Endpoints.Experiment.GetEvalResults(
          experimentInfo.id,
          jobId,
          'view',
          selectedFileIndex,
        )
      : null,
  );

  if (evalFiles.length === 0) {
    return <Typography level="body-sm">No eval results available.</Typography>;
  }

  const headers: string[] = reportData?.header ?? [];
  const rows: unknown[][] = reportData?.body ?? [];

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Typography level="title-md">Eval Results</Typography>
        {evalFiles.length > 1 && (
          <Select
            size="sm"
            value={selectedFileIndex}
            onChange={(_, val) => setSelectedFileIndex(val ?? 0)}
          >
            {evalFiles.map((f, i) => (
              <Option key={i} value={i}>
                {f.split('/').pop()}
              </Option>
            ))}
          </Select>
        )}
      </Box>

      {reportLoading ? (
        <CircularProgress size="sm" />
      ) : headers.length > 0 ? (
        <Box sx={{ overflowX: 'auto' }}>
          <Table size="sm" borderAxis="bothBetween">
            <thead>
              <tr>
                {headers.map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i}>
                  {(row as unknown[]).map((cell, j) => (
                    <td key={j}>{String(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </Table>
        </Box>
      ) : (
        <Typography level="body-sm">No data in this file.</Typography>
      )}
    </Box>
  );
}
