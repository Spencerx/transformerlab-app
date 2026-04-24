/* eslint-disable react/require-default-props */
import React, { useEffect, useState } from 'react';
import {
  Box,
  Button,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormHelperText,
  FormLabel,
  Input,
  Modal,
  ModalClose,
  ModalDialog,
  Sheet,
  Stack,
  Typography,
} from '@mui/joy';
import { useAuth } from 'renderer/lib/authContext';
import { useNotification } from 'renderer/components/Shared/NotificationSystem';

type ProviderConfig = Record<string, unknown> & {
  resource_groups?: unknown;
};

type ProviderLike = {
  id: string;
  name: string;
  config?: ProviderConfig | null;
};

type ResourceGroupEditorValue = {
  id: string;
  name: string;
  cpus: string;
  memory: string;
  disk_space: string;
  accelerators: string;
  num_nodes: string;
};

type ResourceGroupValidation = {
  name?: string;
  resources?: string;
};

interface ProviderResourceGroupsModalProps {
  open: boolean;
  onClose: () => void;
  provider: ProviderLike;
  onSaved?: (provider?: unknown) => void;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function createResourceGroupId(): string {
  return `resource-group-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function emptyResourceGroup(): ResourceGroupEditorValue {
  return {
    id: createResourceGroupId(),
    name: '',
    cpus: '',
    memory: '',
    disk_space: '',
    accelerators: '',
    num_nodes: '',
  };
}

function normalizeResourceGroups(value: unknown): ResourceGroupEditorValue[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value
    .filter((group) => isPlainObject(group))
    .map((group) => ({
      id:
        typeof group.id === 'string' && group.id.trim()
          ? group.id
          : createResourceGroupId(),
      name: typeof group.name === 'string' ? group.name : '',
      cpus: group.cpus != null ? String(group.cpus) : '',
      memory: group.memory != null ? String(group.memory) : '',
      disk_space: group.disk_space != null ? String(group.disk_space) : '',
      accelerators:
        group.accelerators != null ? String(group.accelerators) : '',
      num_nodes: group.num_nodes != null ? String(group.num_nodes) : '',
    }));
}

function validateResourceGroups(
  groups: ResourceGroupEditorValue[],
): ResourceGroupValidation[] {
  const trimmedNames = groups.map((group) => group.name.trim());
  const nameCounts = trimmedNames.reduce<Record<string, number>>(
    (counts, name) => {
      if (!name) {
        return counts;
      }

      const key = name.toLowerCase();
      return {
        ...counts,
        [key]: (counts[key] ?? 0) + 1,
      };
    },
    {},
  );

  return groups.map((group, index) => {
    const name = trimmedNames[index];
    const hasAnyResource = [
      group.cpus,
      group.memory,
      group.disk_space,
      group.accelerators,
      group.num_nodes,
    ].some((fieldValue) => fieldValue.trim() !== '');

    const groupErrors: ResourceGroupValidation = {};

    if (!name) {
      groupErrors.name = 'Name is required.';
    } else if ((nameCounts[name.toLowerCase()] ?? 0) > 1) {
      groupErrors.name = 'Name must be unique within this provider.';
    }

    if (!hasAnyResource) {
      groupErrors.resources = 'Set at least one resource field.';
    }

    return groupErrors;
  });
}

function hasValidationErrors(errors: ResourceGroupValidation[]): boolean {
  return errors.some(
    (groupErrors) => !!groupErrors.name || !!groupErrors.resources,
  );
}

function serializeResourceGroups(groups: ResourceGroupEditorValue[]) {
  return groups.map((group) => {
    const serialized: Record<string, string | number> = {
      id: group.id,
      name: group.name.trim(),
    };

    if (group.cpus.trim()) {
      serialized.cpus = group.cpus.trim();
    }
    if (group.memory.trim()) {
      serialized.memory = group.memory.trim();
    }
    if (group.disk_space.trim()) {
      serialized.disk_space = group.disk_space.trim();
    }
    if (group.accelerators.trim()) {
      serialized.accelerators = group.accelerators.trim();
    }
    if (group.num_nodes.trim()) {
      const parsedNumNodes = Number(group.num_nodes.trim());
      serialized.num_nodes = Number.isNaN(parsedNumNodes)
        ? group.num_nodes.trim()
        : parsedNumNodes;
    }

    return serialized;
  });
}

export default function ProviderResourceGroupsModal({
  open,
  onClose,
  provider,
  onSaved,
}: ProviderResourceGroupsModalProps) {
  const { fetchWithAuth } = useAuth();
  const { addNotification } = useNotification();
  const [groups, setGroups] = useState<ResourceGroupEditorValue[]>([]);
  const [validationErrors, setValidationErrors] = useState<
    ResourceGroupValidation[]
  >([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }

    const providerConfig = isPlainObject(provider.config)
      ? provider.config
      : {};
    setGroups(normalizeResourceGroups(providerConfig.resource_groups));
    setValidationErrors([]);
    setSaving(false);
  }, [open, provider]);

  const updateGroup = (
    index: number,
    field: keyof ResourceGroupEditorValue,
    value: string,
  ) => {
    setGroups((currentGroups) =>
      currentGroups.map((group, groupIndex) =>
        groupIndex === index ? { ...group, [field]: value } : group,
      ),
    );

    setValidationErrors((currentErrors) =>
      currentErrors.map((groupErrors, groupIndex) =>
        groupIndex === index
          ? {
              ...groupErrors,
              ...(field === 'name' ? { name: undefined } : {}),
              resources: undefined,
            }
          : groupErrors,
      ),
    );
  };

  const handleAddGroup = () => {
    setGroups((currentGroups) => [...currentGroups, emptyResourceGroup()]);
    setValidationErrors((currentErrors) => [...currentErrors, {}]);
  };

  const handleDeleteGroup = (index: number) => {
    setGroups((currentGroups) =>
      currentGroups.filter((_, groupIndex) => groupIndex !== index),
    );
    setValidationErrors((currentErrors) =>
      currentErrors.filter((_, groupIndex) => groupIndex !== index),
    );
  };

  const handleSave = async () => {
    const nextValidationErrors = validateResourceGroups(groups);
    setValidationErrors(nextValidationErrors);

    if (hasValidationErrors(nextValidationErrors)) {
      return;
    }

    setSaving(true);

    try {
      const existingConfig = isPlainObject(provider.config)
        ? provider.config
        : {};
      const response = await fetchWithAuth(
        `compute_provider/providers/${provider.id}`,
        {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            name: provider.name,
            config: {
              ...existingConfig,
              resource_groups: serializeResourceGroups(groups),
            },
          }),
        },
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const detail =
          typeof errorData?.detail === 'string'
            ? errorData.detail
            : 'Could not save resource groups.';
        addNotification({ type: 'danger', message: detail });
        return;
      }

      const savedProvider = await response.json().catch(() => undefined);
      addNotification({
        type: 'success',
        message: 'Provider resource groups saved.',
      });
      onSaved?.(savedProvider);
      onClose();
    } catch (error) {
      addNotification({
        type: 'danger',
        message: 'Could not save resource groups.',
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose}>
      <ModalDialog sx={{ width: 900, maxWidth: '95vw' }}>
        <ModalClose />
        <DialogTitle>Provider Resource Groups</DialogTitle>
        <DialogContent>
          <Typography level="body-sm" sx={{ color: 'text.tertiary', mb: 1 }}>
            Manage saved resource presets for `{provider.name}`.
          </Typography>

          <Stack spacing={2}>
            {groups.length === 0 ? (
              <Sheet
                variant="soft"
                sx={{
                  p: 2,
                  borderRadius: 'sm',
                }}
              >
                <Typography level="body-sm">
                  No resource groups defined yet. Add one to save reusable
                  provider presets.
                </Typography>
              </Sheet>
            ) : null}

            {groups.map((group, index) => {
              const groupErrors = validationErrors[index] ?? {};

              return (
                <Sheet
                  key={group.id}
                  variant="outlined"
                  sx={{ p: 2, borderRadius: 'sm' }}
                >
                  <Box role="group" aria-label={`Resource group ${index + 1}`}>
                    <Stack spacing={1.5}>
                      <Stack
                        direction="row"
                        justifyContent="space-between"
                        alignItems="center"
                      >
                        <Typography level="title-md">
                          {group.name.trim() || `Resource Group ${index + 1}`}
                        </Typography>
                        <Button
                          size="sm"
                          color="danger"
                          variant="outlined"
                          onClick={() => handleDeleteGroup(index)}
                        >
                          Delete Group
                        </Button>
                      </Stack>

                      <Box
                        sx={{
                          display: 'grid',
                          gridTemplateColumns: {
                            xs: '1fr',
                            md: 'repeat(2, minmax(0, 1fr))',
                          },
                          gap: 1.5,
                        }}
                      >
                        <FormControl required error={!!groupErrors.name}>
                          <FormLabel>Name</FormLabel>
                          <Input
                            aria-label="Group name"
                            value={group.name}
                            onChange={(event) =>
                              updateGroup(
                                index,
                                'name',
                                event.currentTarget.value,
                              )
                            }
                          />
                          {groupErrors.name ? (
                            <FormHelperText>{groupErrors.name}</FormHelperText>
                          ) : null}
                        </FormControl>

                        <FormControl>
                          <FormLabel>CPUs</FormLabel>
                          <Input
                            aria-label="CPUs"
                            value={group.cpus}
                            onChange={(event) =>
                              updateGroup(
                                index,
                                'cpus',
                                event.currentTarget.value,
                              )
                            }
                          />
                        </FormControl>

                        <FormControl>
                          <FormLabel>Memory</FormLabel>
                          <Input
                            aria-label="Memory"
                            value={group.memory}
                            onChange={(event) =>
                              updateGroup(
                                index,
                                'memory',
                                event.currentTarget.value,
                              )
                            }
                          />
                        </FormControl>

                        <FormControl>
                          <FormLabel>Disk Space</FormLabel>
                          <Input
                            aria-label="Disk space"
                            value={group.disk_space}
                            onChange={(event) =>
                              updateGroup(
                                index,
                                'disk_space',
                                event.currentTarget.value,
                              )
                            }
                          />
                        </FormControl>

                        <FormControl>
                          <FormLabel>Accelerators</FormLabel>
                          <Input
                            aria-label="Accelerators"
                            value={group.accelerators}
                            onChange={(event) =>
                              updateGroup(
                                index,
                                'accelerators',
                                event.currentTarget.value,
                              )
                            }
                          />
                        </FormControl>

                        <FormControl error={!!groupErrors.resources}>
                          <FormLabel>Nodes</FormLabel>
                          <Input
                            aria-label="Nodes"
                            value={group.num_nodes}
                            onChange={(event) =>
                              updateGroup(
                                index,
                                'num_nodes',
                                event.currentTarget.value,
                              )
                            }
                          />
                          {groupErrors.resources ? (
                            <FormHelperText>
                              {groupErrors.resources}
                            </FormHelperText>
                          ) : (
                            <FormHelperText>
                              Set at least one resource field for this group.
                            </FormHelperText>
                          )}
                        </FormControl>
                      </Box>
                    </Stack>
                  </Box>
                </Sheet>
              );
            })}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button variant="outlined" onClick={handleAddGroup}>
            Add Group
          </Button>
          <Box sx={{ flex: 1 }} />
          <Button variant="plain" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSave} loading={saving}>
            Save Resource Groups
          </Button>
        </DialogActions>
      </ModalDialog>
    </Modal>
  );
}
