import * as React from 'react';
import Modal from '@mui/joy/Modal';
import DialogTitle from '@mui/joy/DialogTitle';
import DialogContent from '@mui/joy/DialogContent';
import Button from '@mui/joy/Button';
import {
  ModalClose,
  ModalDialog,
  Divider,
  Stack,
  Sheet,
  List,
  ListItemButton,
  ListItemContent,
  ListItemDecorator,
  Typography,
  Box,
  CircularProgress,
} from '@mui/joy';
import { FileIcon } from 'lucide-react';
import { Editor } from '@monaco-editor/react';
import { setTheme, getMonacoEditorOptions } from 'renderer/lib/monacoConfig';
import * as chatAPI from 'renderer/lib/transformerlab-api-sdk';
import {
  TEXT_FILE_EXTENSIONS,
  getFileExtension,
  getMonacoLanguage,
} from 'renderer/lib/utils';

type FileSource = 'github' | 'local';

interface TaskFile {
  name: string;
  source: FileSource;
}

type TaskYamlEditorModalProps = {
  open: boolean;
  onClose: () => void;
  experimentId: string;
  taskId: string;
  onSaved?: () => void;
};

export default function TaskYamlEditorModal({
  open,
  onClose,
  experimentId,
  taskId,
  onSaved,
}: TaskYamlEditorModalProps) {
  const [content, setContent] = React.useState<string>('');
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [isMissing, setIsMissing] = React.useState(false);
  const [creatingBlank, setCreatingBlank] = React.useState(false);
  const [validationMessage, setValidationMessage] = React.useState<
    string | null
  >(null);
  const [fileList, setFileList] = React.useState<TaskFile[]>([]);
  const [filesLoading, setFilesLoading] = React.useState(false);
  const [selectedFile, setSelectedFile] = React.useState<string | null>(null);

  const isTaskYaml =
    selectedFile === 'task.yaml' || selectedFile === 'task.yml';

  const loadFiles = React.useCallback(async () => {
    if (!experimentId || !taskId) return;
    setFilesLoading(true);
    try {
      const response = await chatAPI.authenticatedFetch(
        chatAPI.Endpoints.Task.ListFiles(experimentId, taskId),
      );
      if (!response.ok) {
        setFileList([]);
        return;
      }
      const data = await response.json();
      const allFiles: TaskFile[] = [];
      if (Array.isArray(data.github_files)) {
        for (const f of data.github_files) {
          allFiles.push({ name: f, source: 'github' });
        }
      }
      if (Array.isArray(data.local_files)) {
        for (const f of data.local_files) {
          allFiles.push({ name: f, source: 'local' });
        }
      }
      setFileList(allFiles);
    } catch {
      setFileList([]);
    } finally {
      setFilesLoading(false);
    }
  }, [experimentId, taskId]);

  const loadFileContent = React.useCallback(
    async (file: TaskFile) => {
      if (!experimentId || !taskId) return;
      setLoading(true);
      setError(null);
      setIsMissing(false);

      // For task.yaml, use the dedicated YAML endpoint
      if (file.name === 'task.yaml' || file.name === 'task.yml') {
        try {
          const response = await chatAPI.authenticatedFetch(
            chatAPI.Endpoints.Task.GetYaml(experimentId, taskId),
          );
          if (!response.ok) {
            if (response.status === 404) {
              setIsMissing(true);
              setContent('');
            } else {
              setIsMissing(true);
              setError(`Failed to load: ${response.status}`);
            }
            return;
          }
          const text = await response.text();
          setContent(text);
        } catch (e) {
          setIsMissing(true);
          setError(e instanceof Error ? e.message : 'Failed to load task.yaml');
        } finally {
          setLoading(false);
        }
        return;
      }

      // For other files, check if it's a renderable text file
      const ext = getFileExtension(file.name);
      if (!TEXT_FILE_EXTENSIONS.has(ext)) {
        setContent('Binary file — preview not available');
        setLoading(false);
        return;
      }

      try {
        const url =
          file.source === 'github'
            ? chatAPI.Endpoints.Task.GetGithubFile(
                experimentId,
                taskId,
                file.name,
              )
            : chatAPI.Endpoints.Task.GetFile(experimentId, taskId, file.name);

        const response = await chatAPI.authenticatedFetch(url);
        if (!response.ok) {
          setError(`Failed to load file: ${response.status}`);
          setContent('');
          return;
        }
        const text = await response.text();
        setContent(text);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load file');
        setContent('');
      } finally {
        setLoading(false);
      }
    },
    [experimentId, taskId],
  );

  // When the modal opens, load file list, then auto-select task.yaml (or first file)
  React.useEffect(() => {
    if (!open || !experimentId || !taskId) return;
    setSelectedFile(null);
    setContent('');
    setError(null);
    setValidationMessage(null);

    (async () => {
      setFilesLoading(true);
      try {
        const response = await chatAPI.authenticatedFetch(
          chatAPI.Endpoints.Task.ListFiles(experimentId, taskId),
        );
        if (!response.ok) {
          setFileList([]);
          return;
        }
        const data = await response.json();
        const allFiles: TaskFile[] = [];
        if (Array.isArray(data.github_files)) {
          for (const f of data.github_files) {
            allFiles.push({ name: f, source: 'github' });
          }
        }
        if (Array.isArray(data.local_files)) {
          for (const f of data.local_files) {
            allFiles.push({ name: f, source: 'local' });
          }
        }
        setFileList(allFiles);

        // Auto-select task.yaml, or fall back to first file
        const taskYaml = allFiles.find(
          (f) => f.name === 'task.yaml' || f.name === 'task.yml',
        );
        const initial = taskYaml || allFiles[0];
        if (initial) {
          setSelectedFile(initial.name);
          await loadFileContent(initial);
        } else {
          setLoading(false);
          setIsMissing(true);
        }
      } catch {
        setFileList([]);
        setLoading(false);
        setIsMissing(true);
      } finally {
        setFilesLoading(false);
      }
    })();
  }, [open, experimentId, taskId, loadFileContent]);

  const handleFileSelect = (file: TaskFile) => {
    if (file.name === selectedFile) return;
    setSelectedFile(file.name);
    setValidationMessage(null);
    loadFileContent(file);
  };

  const handleCreateBlank = async () => {
    setCreatingBlank(true);
    setError(null);
    setValidationMessage(null);
    const defaultYaml =
      'name: my-task\nresources:\n  cpus: 2\n  memory: 4\nrun: "echo hello"';

    try {
      const response = await chatAPI.authenticatedFetch(
        chatAPI.Endpoints.Task.UpdateYaml(experimentId, taskId),
        {
          method: 'PUT',
          headers: { 'Content-Type': 'text/plain' },
          body: defaultYaml,
        },
      );
      if (!response.ok) {
        setError(`Failed to create: ${response.status}`);
        return;
      }
      setContent(defaultYaml);
      setIsMissing(false);
      setError(null);
      // Refresh file list since task.yaml now exists
      await loadFiles();
      setSelectedFile('task.yaml');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to create task.yaml');
    } finally {
      setCreatingBlank(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setValidationMessage(null);
    try {
      const response = await chatAPI.authenticatedFetch(
        chatAPI.Endpoints.Task.UpdateYaml(experimentId, taskId),
        {
          method: 'PUT',
          headers: { 'Content-Type': 'text/plain' },
          body: content,
        },
      );
      if (!response.ok) {
        let message = `Failed to save: ${response.status}`;
        try {
          const contentType = response.headers.get('content-type') || '';
          if (contentType.includes('application/json')) {
            const data = await response.json();
            if (typeof data?.detail === 'string') {
              message = data.detail;
            }
          } else {
            const text = await response.text();
            if (text) {
              message = text;
            }
          }
        } catch {
          // Fallback to default message
        }
        setError(message);
        return;
      }
      onSaved?.();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    setError(null);
    setValidationMessage(null);
    try {
      const response = await chatAPI.authenticatedFetch(
        chatAPI.Endpoints.Task.ValidateYaml(experimentId),
        {
          method: 'POST',
          headers: { 'Content-Type': 'text/plain' },
          body: content,
        },
      );
      if (!response.ok) {
        let message = `Validation failed: ${response.status}`;
        try {
          const contentType = response.headers.get('content-type') || '';
          if (contentType.includes('application/json')) {
            const data = await response.json();
            if (typeof data?.detail === 'string') {
              message = data.detail;
            }
          } else {
            const text = await response.text();
            if (text) {
              message = text;
            }
          }
        } catch {
          // ignore parse errors
        }
        setError(message);
        return;
      }
      setValidationMessage('YAML is valid.');
    } catch (e) {
      setError(
        e instanceof Error
          ? `Validation failed: ${e.message}`
          : 'Validation failed',
      );
    }
  };

  const editorLanguage = selectedFile
    ? getMonacoLanguage(selectedFile)
    : 'yaml';

  return (
    <Modal open={open} onClose={onClose}>
      <ModalDialog
        sx={{
          maxWidth: 1200,
          width: '95vw',
          height: '85vh',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <ModalClose />
        <DialogTitle>Edit Task</DialogTitle>
        <Divider />
        <DialogContent
          sx={{
            flex: 1,
            minHeight: 0,
            p: 0,
            display: 'flex',
            flexDirection: 'row',
          }}
        >
          {/* File list sidebar */}
          <Sheet
            variant="outlined"
            sx={{
              flex: 2,
              minWidth: 180,
              overflow: 'auto',
              borderRadius: 0,
              borderTop: 'none',
              borderBottom: 'none',
              borderLeft: 'none',
            }}
          >
            {filesLoading ? (
              <Box
                sx={{
                  display: 'flex',
                  justifyContent: 'center',
                  alignItems: 'center',
                  py: 4,
                }}
              >
                <CircularProgress size="sm" />
              </Box>
            ) : fileList.length === 0 ? (
              <Box sx={{ p: 2, textAlign: 'center' }}>
                <Typography level="body-sm" color="neutral">
                  No files found
                </Typography>
              </Box>
            ) : (
              <List size="sm">
                {fileList.map((file) => (
                  <ListItemButton
                    key={file.name}
                    selected={selectedFile === file.name}
                    onClick={() => handleFileSelect(file)}
                  >
                    <ListItemDecorator>
                      <FileIcon size={14} />
                    </ListItemDecorator>
                    <ListItemContent>
                      <Typography
                        level="body-sm"
                        sx={{
                          whiteSpace: 'nowrap',
                          textOverflow: 'ellipsis',
                          overflow: 'hidden',
                        }}
                      >
                        {file.name}
                      </Typography>
                    </ListItemContent>
                  </ListItemButton>
                ))}
              </List>
            )}
          </Sheet>

          {/* Editor panel */}
          <Box
            sx={{
              flex: 7,
              minWidth: 0,
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            <Box sx={{ flex: 1, minHeight: 0 }}>
              {loading ? (
                <div style={{ padding: 16 }}>Loading...</div>
              ) : isMissing ? (
                <div
                  style={{
                    padding: 16,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '100%',
                    gap: 16,
                  }}
                >
                  <div
                    style={{
                      color: 'var(--joy-palette-neutral-600)',
                      textAlign: 'center',
                    }}
                  >
                    {error ? (
                      <>
                        <div style={{ marginBottom: 8, fontWeight: 500 }}>
                          Failed to load task.yaml
                        </div>
                        <div
                          style={{
                            fontSize: '0.875rem',
                            color: 'var(--joy-palette-danger-500)',
                          }}
                        >
                          {error}
                        </div>
                      </>
                    ) : (
                      <div style={{ fontWeight: 500 }}>task.yaml not found</div>
                    )}
                    <div style={{ marginTop: 16, fontSize: '0.875rem' }}>
                      Create a blank task.yaml with a sample template?
                    </div>
                  </div>
                  <Button
                    color="primary"
                    variant="solid"
                    onClick={handleCreateBlank}
                    loading={creatingBlank}
                    disabled={creatingBlank}
                  >
                    Create Blank
                  </Button>
                </div>
              ) : (
                <Editor
                  height="100%"
                  language={editorLanguage}
                  value={content}
                  onChange={(v) => setContent(v ?? '')}
                  onMount={(editor, monaco) => {
                    setTheme(editor, monaco);
                  }}
                  options={{
                    ...getMonacoEditorOptions(),
                    readOnly: !isTaskYaml,
                  }}
                />
              )}
            </Box>
            <Divider />
            <Box
              sx={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 1,
                p: 1.5,
              }}
            >
              <div
                style={{
                  minHeight: '1.25rem',
                  flex: 1,
                  fontSize: '0.875rem',
                  color: error
                    ? 'var(--joy-palette-danger-600)'
                    : 'var(--joy-palette-success-600)',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
                title={error || undefined}
              >
                {error || validationMessage}
              </div>
              <Stack direction="row" spacing={1} alignItems="center">
                {isTaskYaml && (
                  <Button
                    color="primary"
                    variant="outlined"
                    onClick={handleValidate}
                    disabled={loading || isMissing || saving}
                  >
                    Validate
                  </Button>
                )}
                {isTaskYaml && (
                  <Button
                    color="success"
                    onClick={handleSave}
                    loading={saving}
                    disabled={loading || isMissing}
                  >
                    Save
                  </Button>
                )}
              </Stack>
            </Box>
          </Box>
        </DialogContent>
      </ModalDialog>
    </Modal>
  );
}
