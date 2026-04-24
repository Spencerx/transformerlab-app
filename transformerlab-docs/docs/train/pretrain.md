---
sidebar_position: 3
unlisted: true
---

# Pre-Training

The Nanotron Pre-training Framework plugin allows you to pre-train models on a single or multi-GPU setup using Transformer Lab. After training, the model will be available in the Foundation tab for further preference training or chatting. It is uses [Nanotron](https://github.com/huggingface/nanotron) for pre-training.

## Step 1: Installing the Plugin

1. Open the `Plugins` tab.
2. Filter by trainer plugins.
3. Install the `Nanotron Pre-training Framework` plugin.

**Note:** This plugin supports both single and multi-GPU setups.

<img src={require('./gifs/pretrain/1_InstallingPlugin.gif').default} alt="Plugin Gif" width="500" />

## Step 2: Creating a Pre-training Task

1. Navigate to the `Train` tab.
2. Click on the `New` button.
3. In the pop-up, complete the following sections:

   - **Name:**  
     Set a unique name for your pre-training task. This will be set as the name of your pre-trained model followed by the job id.

   - **Dataset Tab:**  
     Select the dataset to use for training. A simple and small dataset for pre-training tests is:  
     `stas/openwebtext-10k` (contains 10M tokens).

   - **Data Template Tab:**  
     Specify the column representing the text data.  
     For example, if the dataset has a text column, set the **Formatting Template** to:

     ```markdown
     {{text}}
     ```

## Step 3: Configuring Plugin Parameters

In the **Plugin Config Tab**, configure the following parameters:

- **Training Device:**  
  Set the device for training.  
  _Example:_ `"cuda"`  
  _(Only `cuda` is supported currently)_

- **Random Seed:**  
  Set the seed for reproducibility.  
  _Default:_ `42`

- **Checkpoint Interval (steps):**  
  Determines how often a checkpoint is saved.  
  _Default:_ `1000`

- **Dataset Split:**  
  Specify which part of the dataset to use.  
  _Default:_ `"train"`

- **Text Column Name (in Dataset):**  
  Name of the column with text data.  
  _Default:_ `"text"`

- **Tokenizer Name or Path:**  
  Set the tokenizer.  
  _Default:_ `"robot-test/dummy-tokenizer-wordlevel"`

- **Maximum Sequence Length:**  
  Maximum tokens per sequence.  
  _Default:_ `256`, _(range: 128 - 8192)_

- **Model Hidden Size:**  
  Dimensionality of the model's hidden layers.  
  _Default:_ `16`, _(range: 16 - 8192)_

- **Number of Hidden Layers:**  
  Total hidden layers in the model.  
  _Default:_ `2`, _(minimum: 2)_

- **Number of Attention Heads:**  
  Total attention heads.  
  _Default:_ `4`, _(minimum: 2)_

- **Number of KV Heads (for GQA):**  
  KV Heads for Grouped Query Attention.  
  _Default:_ `4`, _(minimum: 2)_

- **Intermediate Size:**  
  Size of the feed-forward network.  
  _Default:_ `64`, _(minimum: 16)_

- **Micro Batch Size:**  
  Number of samples per micro batch.  
  _Default:_ `2`,

- **Total Training Steps:**  
  Total number of steps for training.  
  _Default:_ `9500`

- **Learning Rate:**  
  Initial learning rate.  
  _Default:_ `5e-4`

- **Warmup Steps:**  
  Steps for the warmup phase.  
  _Default:_ `2`

- **Annealing Phase Start Step:**  
  Step to start the annealing phase.  
  _Default:_ `10`

- **Weight Decay:**  
  Regularization parameter.  
  _Default:_ `0.01`

- **Data Parallel Size:**  
  Number of GPUs for data parallelism.  
  _Default:_ `2`

- **Tensor Parallel Size:**  
  Number of GPUs for tensor parallelism.  
  _Default:_ `1`

- **Pipeline Parallel Size:**  
  Number of GPUs for pipeline parallelism.  
  _Default:_ `1`

- **Mixed Precision Type:**  
  Floating point precision mode.  
  Options: `bfloat16`, `float32`, `float64`  
  _Default:_ `bfloat16`

**Note**: The product of the configs **Data Parallel Size**, **Tensor Parallel Size**, and **Pipeline Parallel Size** should be equal to the total number of GPUs available.

<img src={require('./gifs/pretrain/2_CreatingTask.gif').default} alt="Plugin Gif" width="500" />

## Step 4: Queue and Run the Pre-training Task

After configuring your task:

1. Save the pre-training template by clicking on **Save Training Template**.
2. Click on **Queue** to start the pre-training job.

<img src={require('./gifs/pretrain/3_RunningTask.gif').default} alt="Plugin Gif" width="500" />

## Step 5: Post-training

Once the training finishes, the pre-trained model is available in the Foundation tab. You can then use this model for further preference training or for interactive chatting.

<img src={require('./gifs/pretrain/4_PostTraining.gif').default} alt="Plugin Gif" width="500" />
