import { useState, useEffect, useCallback, useRef } from 'react';
import MDEditor from '@uiw/react-md-editor';

import { useSWRWithAuth as useSWR } from 'renderer/lib/authContext';
import { fetcher } from 'renderer/lib/transformerlab-api-sdk';
import * as chatAPI from 'renderer/lib/transformerlab-api-sdk';
import { authenticatedFetch } from 'renderer/lib/api-client/functions';
import { useExperimentInfo } from 'renderer/lib/ExperimentInfoContext.js';

import Sheet from '@mui/joy/Sheet';
import Box from '@mui/joy/Box';
import Button from '@mui/joy/Button';
import Chip from '@mui/joy/Chip';
import Typography from '@mui/joy/Typography';

export default function ExperimentNotes() {
  const { experimentInfo } = useExperimentInfo();
  const [value, setValue] = useState<string>('');
  const [isDirty, setIsDirty] = useState(false);
  const isDirtyRef = useRef(false);
  const [isSaving, setIsSaving] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const experimentId: string = experimentInfo?.id ?? '';

  const { data, mutate } = useSWR(
    experimentId ? chatAPI.Endpoints.Experiment.GetNotes(experimentId) : null,
    fetcher,
  );

  useEffect(() => {
    if (data !== undefined && !isDirtyRef.current) {
      setValue(typeof data === 'string' ? data : '');
    }
  }, [data]);

  const transformImageSrc = useCallback(
    (src: string | undefined): string => {
      if (!src) return '';
      if (src.startsWith('notes/assets/')) {
        const filename = src.slice('notes/assets/'.length);
        return chatAPI.Endpoints.Experiment.GetNoteAsset(
          experimentId,
          filename,
        );
      }
      return src;
    },
    [experimentId],
  );

  async function saveNotes() {
    setIsSaving(true);
    try {
      const response = await authenticatedFetch(
        chatAPI.Endpoints.Experiment.SaveNotes(experimentId),
        {
          method: 'POST',
          body: JSON.stringify(value || ' '),
          headers: { 'Content-Type': 'application/json' },
        },
      );
      if (!response.ok)
        throw new Error(`HTTP error! status: ${response.status}`);
      await mutate();
      setIsDirty(false);
      isDirtyRef.current = false;
    } catch (err) {
      console.error('Error saving notes:', err);
    } finally {
      setIsSaving(false);
    }
  }

  async function uploadImage(file: File) {
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await authenticatedFetch(
        chatAPI.Endpoints.Experiment.UploadNoteAsset(experimentId),
        { method: 'POST', body: formData },
      );
      if (!response.ok) return;
      const { path } = await response.json();
      const filename = (path as string).replace('notes/assets/', '');
      const insert = `\n![${filename}](${path})\n`;
      setValue((prev) => prev + insert);
      setIsDirty(true);
      isDirtyRef.current = true;
    } catch (err) {
      console.error('Error uploading image:', err);
    }
  }

  function handlePaste(e: React.ClipboardEvent) {
    const items = Array.from(e.clipboardData.items);
    const imageItem = items.find((item) => item.type.startsWith('image/'));
    if (!imageItem) return;
    e.preventDefault();
    const file = imageItem.getAsFile();
    if (!file) return;
    const ext = file.type.split('/')[1] || 'png';
    const namedFile = new File([file], `pasted-${Date.now()}.${ext}`, {
      type: file.type,
    });
    uploadImage(namedFile);
  }

  if (!experimentInfo?.id) return null;

  return (
    <Sheet
      sx={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        p: 2,
      }}
    >
      <Box
        display="flex"
        justifyContent="space-between"
        alignItems="center"
        mb={1}
      >
        <Typography level="h3">Experiment Notes</Typography>
        <Box display="flex" gap={1} alignItems="center">
          {isDirty && (
            <Chip color="warning" size="sm">
              Unsaved changes
            </Chip>
          )}
          <Button
            size="sm"
            variant="outlined"
            onClick={() => fileInputRef.current?.click()}
          >
            Upload Image
          </Button>
          <Button
            size="sm"
            color="success"
            onClick={saveNotes}
            loading={isSaving}
            disabled={!isDirty}
          >
            Save
          </Button>
        </Box>
      </Box>

      <input
        ref={fileInputRef}
        type="file"
        accept=".png,.jpg,.jpeg,.gif,.svg"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) uploadImage(file);
          e.target.value = '';
        }}
      />

      <Box
        data-color-mode="dark"
        onPaste={handlePaste}
        sx={{
          flex: 1,
          overflow: 'hidden',
          '& .w-md-editor': { height: '100% !important' },
        }}
      >
        <MDEditor
          value={value}
          onChange={(val) => {
            setValue(val ?? '');
            setIsDirty(true);
            isDirtyRef.current = true;
          }}
          preview="live"
          height="100%"
          previewOptions={{
            components: {
              img: ({
                src,
                alt,
                ...props
              }: React.ImgHTMLAttributes<HTMLImageElement>) => (
                // eslint-disable-next-line jsx-a11y/alt-text
                <img src={transformImageSrc(src)} alt={alt} {...props} />
              ),
            },
          }}
        />
      </Box>
    </Sheet>
  );
}
