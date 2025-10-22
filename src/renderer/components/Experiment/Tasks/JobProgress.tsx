import {
  Box,
  Chip,
  IconButton,
  LinearProgress,
  Stack,
  Typography,
} from '@mui/joy';
import { CircleCheckIcon, StopCircleIcon } from 'lucide-react';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import duration from 'dayjs/plugin/duration';
import { jobChipColor } from 'renderer/lib/utils';
import { useEffect } from 'react';
import { useExperimentInfo } from 'renderer/lib/ExperimentInfoContext';
dayjs.extend(relativeTime);
dayjs.extend(duration);
import * as chatAPI from 'renderer/lib/transformerlab-api-sdk';

interface JobData {
  start_time?: string;
  end_time?: string;
  completion_status?: string;
  completion_details?: string;
  [key: string]: any;
}

interface JobProps {
  job: {
    id: string;
    status: string;
    progress: string | number;
    job_data?: JobData;
  };
}

export default function JobProgress({ job }: JobProps) {
  const { experimentInfo } = useExperimentInfo();
  // Debug job data
  useEffect(() => {}, [job]);

  // Ensure progress is a number
  const progress =
    typeof job?.progress === 'string'
      ? parseFloat(job.progress)
      : typeof job?.progress === 'number'
        ? job.progress
        : 0;

  return (
    <Stack>
      {job?.status === 'RUNNING' ? (
        <>
          <Stack direction={'row'} alignItems="center" gap={1}>
            <Chip
              sx={{
                backgroundColor: jobChipColor(job.status),
                color: 'var(--joy-palette-neutral-800)',
              }}
            >
              {job.status}
            </Chip>
            {progress === -1 ? '' : progress.toFixed(1) + '%'}
            <LinearProgress determinate value={progress} sx={{ my: 1 }} />
            <IconButton
              color="danger"
              onClick={async () => {
                if (confirm('Are you sure you want to stop this job?')) {
                  if (job.type === 'REMOTE') {
                    // For REMOTE jobs, use the remote stop endpoint
                    const cluster_name = job.job_data?.cluster_name;
                    if (cluster_name) {
                      const formData = new FormData();
                      formData.append('job_id', job.id);
                      formData.append('cluster_name', cluster_name);
                      await chatAPI.authenticatedFetch(
                        chatAPI.Endpoints.Jobs.StopRemote(),
                        { method: 'POST', body: formData },
                      );
                    } else {
                      console.error('No cluster_name found in REMOTE job data');
                    }
                  } else {
                    // For other job types, use the regular stop endpoint
                    await chatAPI.authenticatedFetch(
                      chatAPI.Endpoints.Jobs.Stop(experimentInfo.id, job.id),
                    );
                  }
                }
              }}
            >
              <StopCircleIcon size="20px" />
            </IconButton>
          </Stack>
          {/* Add smaller sweep subprogress bar when job.progress is -1 */}
          {job.progress === '-1' &&
            job?.job_data?.hasOwnProperty('sweep_subprogress') && (
              <Stack
                direction="row"
                alignItems="center"
                gap={1}
                sx={{ mt: 0.5 }}
              >
                {/* <Typography level="body-sm">
                  Sweep progress {job.job_data.sweep_current}/
                  {job.job_data.sweep_total}:
                </Typography> */}
                <Chip
                  size="sm"
                  variant="soft"
                  color="primary"
                  sx={{
                    fontSize: 'var(--joy-fontSize-xs)',
                    height: 'auto',
                    py: 0.5,
                  }}
                >
                  Sweep {job.job_data.sweep_current}/{job.job_data.sweep_total}
                </Chip>
                <LinearProgress
                  determinate
                  value={job.job_data.sweep_subprogress}
                  sx={{
                    my: 0.5,
                    height: '4px', // Make it smaller than the main progress bar
                  }}
                />
                {`${Number.parseFloat(job.job_data.sweep_subprogress).toFixed(1)}%`}
              </Stack>
            )}
          {job?.job_data?.start_time && (
            <>
              Started:{' '}
              {dayjs(job?.job_data?.start_time).format('MMM D, YYYY HH:mm:ss')}
            </>
          )}
          <Box
            sx={{
              display: 'flex',
              flexDirection: 'row',
              flexWrap: 'wrap',
              columnGap: 1,
              mt: 1,
            }}
          >
            {[
              'Machine with Appropriate Resources Found',
              'IP Address Allocated',
              'Machine Provisioning Complete',
              'Environment Setup Complete',
              'Job Deployed Using Ray',
              'Shared Disk Mounted',
              'Lab SDK Initialized',
            ].map((text) => (
              <Typography
                key={text}
                level="body-sm"
                alignItems="center"
                display="flex"
                startDecorator={<CircleCheckIcon size="16px" />}
                color="primary"
              >
                {text}
              </Typography>
            ))}
          </Box>
        </>
      ) : (
        <Stack direction="column" justifyContent="space-between">
          <>
            <Chip
              sx={{
                backgroundColor: jobChipColor(job.status),
                color: 'var(--joy-palette-neutral-800)',
              }}
            >
              {job.status}
              {progress === -1 ? '' : ` - ${progress.toFixed(1)}%`}
            </Chip>
            {job?.job_data?.start_time && (
              <>
                Started:{' '}
                {dayjs(job?.job_data?.start_time).format(
                  'MMM D, YYYY HH:mm:ss',
                )}{' '}
                <br />
              </>
            )}
            {job?.job_data?.end_time && job?.job_data?.end_time && (
              <>
                Completed in:{' '}
                {dayjs
                  .duration(
                    dayjs(job?.job_data?.end_time).diff(
                      dayjs(job?.job_data?.start_time),
                    ),
                  )
                  .humanize()}{' '}
                <br />
              </>
            )}
            {job?.status === 'COMPLETE' &&
              (job?.job_data?.completion_status ? (
                <>
                  {/* Final Status:{' '} */}
                  {job?.job_data?.completion_status == 'success' ? (
                    <Typography level="body-sm" color="success">
                      Success: {job?.job_data?.completion_details}
                    </Typography>
                  ) : (
                    <Typography level="body-sm" color="danger">
                      Failure: {job?.job_data?.completion_details}
                    </Typography>
                  )}
                </>
              ) : (
                /* If we don't have a status, assume it failed */
                <Typography level="body-sm" color="neutral">
                  No job completion status. Task may have failed. View output
                  for details
                </Typography>
              ))}
          </>
        </Stack>
      )}
    </Stack>
  );
}
