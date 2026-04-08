import { useState } from 'react';
import {
  Modal,
  ModalDialog,
  ModalClose,
  Typography,
  Divider,
  Box,
  Stack,
} from '@mui/joy';
import { DatabaseIcon, FileTextIcon, ArchiveIcon } from 'lucide-react';
import ViewArtifactsModal from './ViewArtifactsModal';
import ViewJobDatasetsModal from './ViewJobDatasetsModal';
import ViewJobModelsModal from './ViewJobModelsModal';

interface ViewJobArtifactsTabbedModalProps {
  open: boolean;
  onClose: () => void;
  jobId: string | null;
}

export default function ViewJobArtifactsTabbedModal({
  open,
  onClose,
  jobId,
}: ViewJobArtifactsTabbedModalProps) {
  const [modelsCount, setModelsCount] = useState<number | null>(null);
  const [datasetsCount, setDatasetsCount] = useState<number | null>(null);
  const [artifactsCount, setArtifactsCount] = useState<number | null>(null);

  const countLabel = (count: number | null) =>
    count !== null ? ` (${count})` : '';

  return (
    <Modal open={open} onClose={onClose}>
      <ModalDialog
        sx={{
          width: '90vw',
          height: '80vh',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <ModalClose />
        <Typography level="h2" sx={{ mb: 2, mr: 4 }}>
          Artifacts for Job {jobId}
        </Typography>
        <Box sx={{ flex: 1, overflow: 'auto' }}>
          <Stack spacing={3}>
            <section>
              <Stack
                direction="row"
                alignItems="center"
                spacing={1}
                sx={{ mb: 1 }}
              >
                <DatabaseIcon size={18} />
                <Typography level="title-lg">
                  Models{countLabel(modelsCount)}
                </Typography>
              </Stack>
              <ViewJobModelsModal
                open={false}
                onClose={() => {}}
                jobId={jobId}
                renderContentOnly
                onCountLoaded={setModelsCount}
              />
            </section>

            <Divider />

            <section>
              <Stack
                direction="row"
                alignItems="center"
                spacing={1}
                sx={{ mb: 1 }}
              >
                <FileTextIcon size={18} />
                <Typography level="title-lg">
                  Datasets{countLabel(datasetsCount)}
                </Typography>
              </Stack>
              <ViewJobDatasetsModal
                open={false}
                onClose={() => {}}
                jobId={jobId}
                renderContentOnly
                onCountLoaded={setDatasetsCount}
              />
            </section>

            <Divider />

            <section>
              <Stack
                direction="row"
                alignItems="center"
                spacing={1}
                sx={{ mb: 1 }}
              >
                <ArchiveIcon size={18} />
                <Typography level="title-lg">
                  Other Artifacts{countLabel(artifactsCount)}
                </Typography>
              </Stack>
              <ViewArtifactsModal
                open={false}
                onClose={() => {}}
                jobId={jobId}
                renderContentOnly
                onCountLoaded={setArtifactsCount}
              />
            </section>
          </Stack>
        </Box>
      </ModalDialog>
    </Modal>
  );
}
