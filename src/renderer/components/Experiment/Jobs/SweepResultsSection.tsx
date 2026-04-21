import React from 'react';
import Box from '@mui/joy/Box';
import Typography from '@mui/joy/Typography';
import CircularProgress from '@mui/joy/CircularProgress';
import Table from '@mui/joy/Table';
import { useSWRWithAuth } from 'renderer/lib/authContext';
import { useExperimentInfo } from 'renderer/lib/ExperimentInfoContext';
import * as chatAPI from 'renderer/lib/transformerlab-api-sdk';

export default function SweepResultsSection({ jobId }: { jobId: string }) {
  const { experimentInfo } = useExperimentInfo();

  const { data, isLoading } = useSWRWithAuth(
    experimentInfo?.id && jobId
      ? chatAPI.Endpoints.Experiment.GetSweepResults(experimentInfo.id, jobId)
      : null,
  );

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', pt: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!data || data.status === 'error') {
    return (
      <Typography level="body-sm">
        {data?.message ?? 'No sweep results available.'}
      </Typography>
    );
  }

  const results: Record<string, unknown>[] = Array.isArray(data) ? data : [];

  if (results.length === 0) {
    return <Typography level="body-sm">No sweep results available.</Typography>;
  }

  const headers = Object.keys(results[0]);

  return (
    <Box>
      <Typography level="title-md" sx={{ mb: 2 }}>
        Sweep Results
      </Typography>
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
            {results.map((row, i) => (
              <tr key={i}>
                {headers.map((h) => (
                  <td key={h}>{String(row[h] ?? '')}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      </Box>
    </Box>
  );
}
