---
name: terraform-change-checklist
description: Check a Terraform change before the user applies it, and read an apply error afterwards. Use when you change .tf files, the region, a module or .env values in the custom-models repo, when you prepare apply or destroy steps, or when an apply or a Vertex AI deploy fails.
---

# Terraform change checklist

The agent may apply or destroy under the rules of `CLAUDE.md`. It checks the change first, and it uses the README steps, so the user can run the same steps by hand.

## Before the apply

1. Run the local checks. They need no credentials.
   ```sh
   ./scripts/check.py            # fmt, validate, terraform test, tflint in every root
   ./scripts/check.py infra/core # one root
   ```
   Fix every FAIL before you go on. These checks find only config errors.
   A new deployment needs `alerts.tf` (module `scale-alerts`): `check.py` fails without it. Apply `infra/core/` first, so the Slack channel `models-slack` exists. See `infra/README.md`, "Add scale alerts to a new deployment".
2. Run the real-world checks. Use a fresh environment: a shell that started before a `.env` change has old values, and the script reports `shell is stale`.
   ```sh
   ./scripts/preflight.py --weights <folder> --l4
   ```
   FAIL means stop. WARN means the script could not check: tell the user what to check by hand (for example the L4 quota in the console).
3. Run `terraform plan` in the root. Read it. Write down every line that says "replaced" or "destroyed".
4. Compare that list with the resources that must never change by accident:
   - the shared API key, the budget, the `hf-token` secret and the gateway APIs (`infra/core`)
   - a bucket that holds weights (it has no `force_destroy` on purpose)
   - a Vertex AI endpoint with a deployed model

   If one of them is in the list, stop and ask the user.
5. A replaced bucket loses its IAM members, because the name stays the same. Check that each `google_storage_bucket_iam_member` has `replace_triggered_by` on its bucket.
6. Give the user the apply steps, in order, with the commands from the README of the root. Do not invent new commands. Say which step is new for this change.

## After the apply

1. Run `terraform plan` again. It must say "No changes". If not, the apply is not finished: read what is left.
2. Run `./scripts/preflight.py` again.
3. Run `./scripts/verify-gcp.py state` and `./scripts/verify-gcp.py smoke` (free). See the `verify-gcp` skill.

## Read an error

| Error | Kind | Action |
|---|---|---|
| `404 ... bucket does not exist` right after the bucket was created | Timing | Apply again. It creates only what is missing. |
| `code 14 ... Machine type temporarily unavailable` | GPU stock | Retry later, or use another machine type or region. See `infra/README.md`. |
| `quota` or `RESOURCE_EXHAUSTED` | Quota | The user asks for more in the console (IAM & Admin > Quotas). |
| `Unreadable module directory`, `organization must be set` | Setup | See skill `hcp-direnv-terraform`. |
| `shell is stale`, or a resource appears in the wrong region | Old environment | Run `direnv reload` or start a new shell. Run `hcp-sync.py` again. |
| `invalid`, `unsupported argument`, a failed test | Config | Fix the code. Run `./scripts/check.py`. |

Do not apply again for a config error. Apply again only for a timing error.

## Region change

1. `./scripts/vertex.py undeploy deployments/<name>` for each Vertex AI deployment.
2. `terraform destroy` in each deployment. Do it while HCP still has the old region.
3. Empty the weights bucket. It has no `force_destroy`.
4. Change `GCP_REGION` in `.env`. Run `direnv reload`. Run `./scripts/hcp-sync.py`. Run `./scripts/preflight.py`: the HCP region must show `ok`.
5. Apply `infra/core`. Run the weights-copy job. Apply each deployment, then `scripts/vertex.py deploy` (it fills the image cache itself; no manual `curl`) and `scripts/gateway-streaming.py`.
6. Run `./scripts/ui-deploy.py`. Update the region in the docs.

Run the L4 quota check (`--l4`) before step 1. After step 1 there is no fallback.
