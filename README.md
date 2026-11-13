# leargas
Repo for the Junction 26 Stoa Track

## Getting the dataset

The dataset is a private Hugging Face dataset: [leargas/junction-dataset](https://huggingface.co/datasets/leargas/junction-dataset). Ask to be added to the `leargas` org.

```powershell
pip install -U huggingface_hub
hf auth login   # Read token from https://huggingface.co/settings/tokens
hf download leargas/junction-dataset --repo-type=dataset --local-dir datasets/junction-dataset
```

`datasets/` is gitignored. Don't commit dataset files.
