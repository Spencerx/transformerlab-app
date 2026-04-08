import { test, expect, Page } from '@playwright/test';
import { login, selectFirstExperiment } from './helpers';

const TASK_NAME = 'sample-generate-task';
const REGISTRY_DATASET_NAME = 'sample-generate-task-registry-dataset';
const REGISTRY_VERSION_NAME = 'sample-generate-task-v1';

const TASK_YAML = `name: sample-generate-task
github_repo_url: https://github.com/transformerlab/transformerlab-examples
github_repo_dir: demo-generate-task
resources:
  cpus: 2
  memory: 4
setup: "uv pip install transformerlab datasets;"
run: "python ~/demo-generate-task/fake_generate.py"
`;

async function replaceMonacoContents(page: Page, contents: string) {
  const editor = page.locator('.monaco-editor').first();
  await expect(editor).toBeVisible({ timeout: 10000 });
  await editor.click();

  // Replace all editor content with the task YAML.
  const selectAllShortcut =
    process.platform === 'darwin' ? 'Meta+A' : 'Control+A';
  await page.keyboard.press(selectAllShortcut);
  await page.keyboard.type(contents);
}

test.describe('Dataset Generation Task', () => {
  test.setTimeout(180_000);

  test('create blank task, edit task.yaml, run local job, save dataset to registry, verify in Datasets page', async ({
    page,
  }) => {
    await login(page);

    await selectFirstExperiment(page);
    await page.getByRole('button', { name: 'Tasks', exact: true }).click();
    await expect(page.getByRole('button', { name: 'New' })).toBeVisible({
      timeout: 10000,
    });

    // Create a blank task.
    await page.getByRole('button', { name: 'New' }).click();
    await expect(
      page.getByRole('dialog', { name: 'Add New Task' }),
    ).toBeVisible();
    await page
      .getByRole('radio', { name: 'Start with a blank task template' })
      .click();
    await page
      .getByRole('dialog', { name: 'Add New Task' })
      .getByRole('button', { name: 'Submit' })
      .click();

    // Edit generated task.yaml to use the dataset generator template.
    const taskYamlDialog = page.getByRole('dialog', { name: 'task.yaml' });
    await expect(taskYamlDialog).toBeVisible({ timeout: 10000 });
    await replaceMonacoContents(page, TASK_YAML);
    await taskYamlDialog.getByRole('button', { name: 'Save' }).click();

    await expect(
      page.getByText(TASK_NAME, { exact: true }).first(),
    ).toBeVisible({ timeout: 15000 });

    const taskRow = page.locator('tr', {
      has: page.getByText(TASK_NAME, { exact: true }),
    });
    await taskRow.first().getByRole('button', { name: 'Queue' }).click();

    const queueDialog = page.getByRole('dialog', { name: /Queue Task/ });
    await expect(queueDialog).toBeVisible({ timeout: 10000 });
    await expect(
      queueDialog.getByRole('combobox', { name: 'Compute Provider' }),
    ).toHaveText('Local', { timeout: 5000 });
    await queueDialog.getByRole('button', { name: 'Submit' }).click();

    // Wait for completion.
    await expect(page.getByText('COMPLETE').first()).toBeVisible({
      timeout: 120000,
    });

    // Open Artifacts -> View Datasets.
    await page.getByRole('button', { name: 'Artifacts' }).first().click();
    await page.getByRole('menuitem', { name: 'View Datasets' }).first().click();

    const datasetsDialog = page.getByRole('dialog');
    await expect(datasetsDialog.getByText('Datasets for Job')).toBeVisible({
      timeout: 10000,
    });
    await expect(
      datasetsDialog.getByText('Save to Registry').first(),
    ).toBeVisible({ timeout: 10000 });
    await datasetsDialog
      .getByRole('button', { name: 'Save to Registry' })
      .first()
      .click();

    const publishDialog = page.getByRole('dialog', {
      name: 'Publish Dataset to Registry',
    });
    await expect(publishDialog).toBeVisible({ timeout: 10000 });
    await publishDialog
      .getByRole('textbox', { name: 'Name' })
      .fill(REGISTRY_DATASET_NAME);
    await publishDialog
      .getByRole('textbox', { name: 'Version Name' })
      .fill(REGISTRY_VERSION_NAME);
    await publishDialog.getByRole('button', { name: /Publish as/i }).click();

    // Wait for publish dialog to close and success state in dataset modal.
    await expect(publishDialog).toBeHidden({ timeout: 20000 });
    await expect(datasetsDialog.getByText(/Successfully saved/i)).toBeVisible({
      timeout: 30000,
    });
    await page.keyboard.press('Escape');

    // Verify fixed dataset registry group appears on Datasets page.
    await page.getByRole('button', { name: 'Datasets' }).click();
    await expect(page.getByText('Dataset Registry')).toBeVisible({
      timeout: 10000,
    });
    await expect(
      page.getByText(REGISTRY_DATASET_NAME, { exact: true }).first(),
    ).toBeVisible({
      timeout: 30000,
    });
  });
});
