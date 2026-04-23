import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Modal,
  ModalClose,
  ModalDialog,
  Typography,
} from '@mui/joy';

interface LocalProviderRefreshModalProps {
  open: boolean;
  onClose: () => void;
  providerName: string;
  setupStatus: string | null;
  setupLogTail: string;
  isInProgress: boolean;
  titlePrefix: string;
  description: string;
}

export default function LocalProviderRefreshModal({
  open,
  onClose,
  providerName,
  setupStatus,
  setupLogTail,
  isInProgress,
  titlePrefix,
  description,
}: LocalProviderRefreshModalProps) {
  let statusColor: 'primary' | 'danger' | 'success' = 'success';
  if (isInProgress) {
    statusColor = 'primary';
  } else if (
    setupStatus?.toLowerCase().includes('failed') ||
    setupStatus?.toLowerCase().includes('error')
  ) {
    statusColor = 'danger';
  }

  return (
    <Modal open={open} onClose={onClose}>
      <ModalDialog sx={{ width: 650, maxWidth: '90vw', maxHeight: '85vh' }}>
        <ModalClose />
        <Typography level="h4">
          {titlePrefix} {providerName || 'Local Provider'}
        </Typography>
        <Typography level="body-sm" sx={{ color: 'text.tertiary', mt: 0.5 }}>
          {description}
        </Typography>
        <Box sx={{ mt: 2 }}>
          {setupStatus && (
            <Alert
              color={statusColor}
              startDecorator={
                isInProgress ? <CircularProgress size="sm" /> : undefined
              }
            >
              {setupStatus}
            </Alert>
          )}
          <Box
            sx={{
              mt: 1.5,
              maxHeight: 360,
              overflow: 'auto',
              borderRadius: 'sm',
              border: '1px solid',
              borderColor: 'neutral.outlinedBorder',
              bgcolor: 'neutral.softBg',
              p: 1.5,
              fontFamily: 'monospace',
              fontSize: '12px',
              whiteSpace: 'pre-wrap',
            }}
          >
            {setupLogTail || 'Waiting for setup logs...'}
          </Box>
        </Box>
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 2 }}>
          <Button variant="outlined" onClick={onClose}>
            Close
          </Button>
        </Box>
      </ModalDialog>
    </Modal>
  );
}
