"""Sample Transformer Lab task.

This file demonstrates the core Lab SDK calls you will use in a real task.
Replace the sleep loop with your actual training / inference / eval code.

Common SDK calls:
  - lab.init()                    attach this process to the job
  - lab.log(message)              stream a line to the task log
  - lab.update_progress(n)        set job progress (0..100)
  - lab.get_config()              read `parameters:` from task.yaml
  - lab.save_artifact(path, name) attach a file to the job (summaries,
                                  plots, CSVs, etc.) for later download
  - lab.save_checkpoint(dir, name) persist a training checkpoint
  - lab.save_model(dir, name=...)  register a final trained model
  - lab.finish(message)            mark the job SUCCESS
  - lab.error(message)             mark the job FAILED

Docs: https://lab.cloud/for-teams/running-a-task/lab-sdk
"""

import json
import time
from pathlib import Path

from lab import lab


def main():
    # Always call init() first. Without it, log / progress / artifact
    # calls will not be associated with the job.
    lab.init()

    try:
        # Read parameters defined under `parameters:` in task.yaml.
        # Returns a dict; use .get() with a default so the task still
        # runs when a parameter is missing.
        config = lab.get_config() or {}
        total_steps = int(config.get("total_steps", 5))

        lab.log(f"Starting task with config: {config}")
        lab.update_progress(5)

        # ----- Fake training loop -----
        # Replace this block with your real work. In a real task you
        # would typically also call:
        #   lab.save_checkpoint(checkpoint_dir, f"checkpoint-{step}")
        # every N steps so the job can resume on retry.
        for step in range(1, total_steps + 1):
            time.sleep(1)  # pretend we are doing something expensive
            progress = 5 + int(step / total_steps * 90)  # 5..95
            lab.log(f"step {step}/{total_steps}")
            lab.update_progress(progress)

        # ----- Save an artifact -----
        # Artifacts are any files you want attached to the job for later
        # download (metrics, plots, CSVs, etc.). The second argument is
        # the name the artifact appears under in the UI / CLI.
        summary_path = Path("training_summary.json")
        summary_path.write_text(json.dumps({"steps": total_steps, "ok": True}, indent=2))
        lab.save_artifact(str(summary_path), "training_summary.json")

        # If you trained a model, you would also call:
        #   lab.save_model(model_dir, name="my_trained_model")

        lab.update_progress(100)
        lab.finish("Task completed successfully")

    except Exception as e:
        # Any unhandled exception should be reported via lab.error so
        # the job is marked FAILED instead of being stuck in RUNNING.
        lab.error(f"Task failed: {e}")
        raise


if __name__ == "__main__":
    main()
