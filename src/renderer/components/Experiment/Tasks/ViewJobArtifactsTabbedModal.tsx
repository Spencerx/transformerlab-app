import {
  Modal,
  ModalDialog,
  ModalClose,
  Typography,
  Tabs,
  TabList,
  Tab,
  TabPanel,
  Box,
} from '@mui/joy';
import { DatabaseIcon, FileTextIcon, ArchiveIcon } from 'lucide-react';
import ViewArtifactsModal from './ViewArtifactsModal';
import ViewJobDatasetsModal from './ViewJobDatasetsModal';
import ViewJobModelsModal from './ViewJobModelsModal';

interface ViewJobArtifactsTabbedModalProps {
  open: boolean;
  onClose: () => void;
  jobId: string | null;
  defaultTab?: number;
}

export default function ViewJobArtifactsTabbedModal({
  open,
  onClose,
  jobId,
  defaultTab = 0,
}: ViewJobArtifactsTabbedModalProps) {
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
        <Tabs
          defaultValue={defaultTab}
          sx={{
            flex: 1,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <TabList>
            <Tab>
              <DatabaseIcon size={16} />
              <Box component="span" sx={{ ml: 0.5 }}>
                Models
              </Box>
            </Tab>
            <Tab>
              <FileTextIcon size={16} />
              <Box component="span" sx={{ ml: 0.5 }}>
                Datasets
              </Box>
            </Tab>
            <Tab>
              <ArchiveIcon size={16} />
              <Box component="span" sx={{ ml: 0.5 }}>
                All Artifacts
              </Box>
            </Tab>
          </TabList>
          <TabPanel value={0} sx={{ flex: 1, overflow: 'auto', p: 2 }}>
            <ViewJobModelsModal
              open={false}
              onClose={() => {}}
              jobId={jobId}
              renderContentOnly
            />
          </TabPanel>
          <TabPanel value={1} sx={{ flex: 1, overflow: 'auto', p: 2 }}>
            <ViewJobDatasetsModal
              open={false}
              onClose={() => {}}
              jobId={jobId}
              renderContentOnly
            />
          </TabPanel>
          <TabPanel value={2} sx={{ flex: 1, overflow: 'auto', p: 2 }}>
            <ViewArtifactsModal
              open={false}
              onClose={() => {}}
              jobId={jobId}
              renderContentOnly
            />
          </TabPanel>
        </Tabs>
      </ModalDialog>
    </Modal>
  );
}
