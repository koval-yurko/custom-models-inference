# Slack Scale Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a Slack message when a model is ready after scale up (0 → 1) and when it scales down (1 → 0), for every deployment.

**Architecture:** `infra/core/` creates one native Slack notification channel. A new module `infra/modules/scale-alerts/` creates 2 log-based alert policies ("ready" and "down") for one model. Each deployment root calls the module and finds the channel through a data source. Vertex AI container logs are turned on, and `llm-b` prints `engine ready`, so each model writes a clear log line.

**Tech Stack:** Terraform `>= 1.7`, provider `hashicorp/google ~> 8.10` (locked 8.10.0), Cloud Monitoring, Cloud Logging, Slack bot app, Python 3 standard library (`scripts/hcp-sync.py`).

**Spec:** `docs/specs/2026-11-19-scale-notifications-slack-design.md`

## Global Constraints

- Provider fields (checked in the 8.10.0 schema): `sensitive_labels.auth_token_wo` and `auth_token_wo_version`; `documentation.subject`, `content`, `mime_type`; `alert_strategy.auto_close`, `notification_prompts`, `notification_rate_limit`; `condition_matched_log.filter`.
- The Slack bot token is never in state: an `ephemeral` + `sensitive` variable into `auth_token_wo`, the same pattern as `hf_token` in `infra/core/weights_copy.tf`.
- Channel display name: `models-slack`. Deployments find it by this name only.
- Message subjects: `🟢 <title> is ready` and `⚪ <title> scaled to 0`.
- `notification_rate_limit.period = "300s"`, `auto_close = "1800s"`, `notification_prompts = ["OPENED"]`.
- One model per root. No public services. No min instances above 0.
- The agent runs `terraform fmt`, `validate`, `terraform test` and `./scripts/check.py`.
- The user allowed the agent to run `terraform apply` for this plan (2026-11-20). Before each apply, run `terraform plan` and stop if it changes more than the task expects. Run it as `direnv exec . terraform apply -auto-approve` in the root.
- `scripts/vertex.py undeploy|deploy`, `gcloud builds submit` and model test calls cost money. The agent runs them only if the user said yes to them before execution. Otherwise the user runs them.
- Docs prose is in Simplified Technical English.
- New `.env` variables: `SLACK_BOT_TOKEN` (sensitive), `SLACK_CHANNEL` (for example `#models`). Never print their values.

## Review Focus

1. A filter that matches the logs of another model sends a wrong message. Each deployment test checks that its filters contain its own service name or endpoint ID (Task 6).
2. A text with a `"` breaks the log filter at apply time. The module rejects it with a validation (Task 1).
3. `SLACK_CHANNEL` without the leading `#` creates a channel that sends nothing. Core rejects it with a validation (Task 2).
4. Vertex AI can write the line in `textPayload` or in `jsonPayload.message`. Each filter matches both fields (Task 1).
5. Cloud Run writes `Application startup complete.` before the startup probe passes. The TTS "ready" filter uses the system log line `STARTUP HTTP probe succeeded`, not the uvicorn line (Task 6).

---

### Task 1: Module `scale-alerts`

**Files:**
- Create: `infra/modules/scale-alerts/versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`
- Test: `infra/modules/scale-alerts/tests/scale_alerts.tftest.hcl`

**Interfaces:**
- Consumes: nothing.
- Produces: module inputs `project_id` (string), `title` (string), `resource_filter` (string), `ready_text` (string), `down_text` (string, default `"Application shutdown complete."`), `notification_channel` (string, channel resource name). Output `filters` = `{ ready = string, down = string }`. Resources `google_monitoring_alert_policy.this["ready"]` and `["down"]`.

- [ ] **Step 1: Write the failing test** `tests/scale_alerts.tftest.hcl` with `mock_provider "google" {}` and these variables: `project_id = "p"`, `title = "Model T"`, `resource_filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"svc\""`, `ready_text = "STARTUP HTTP probe succeeded"`, `notification_channel = "projects/p/notificationChannels/1"`.

  - `run "two_policies_with_filters"` (`command = apply`):
    - `output.filters.ready == "${var.resource_filter} AND (textPayload:\"STARTUP HTTP probe succeeded\" OR jsonPayload.message:\"STARTUP HTTP probe succeeded\")"`
    - `output.filters.down` contains `"Application shutdown complete."` (use `strcontains`).
    - `google_monitoring_alert_policy.this["ready"].conditions[0].condition_matched_log[0].filter == output.filters.ready`
    - `google_monitoring_alert_policy.this["ready"].documentation[0].subject == "🟢 Model T is ready"`
    - `google_monitoring_alert_policy.this["down"].documentation[0].subject == "⚪ Model T scaled to 0"`
  - `run "strategy_and_channel"`: for both keys, `notification_channels == ["projects/p/notificationChannels/1"]`, `alert_strategy[0].notification_rate_limit[0].period == "300s"`, `alert_strategy[0].auto_close == "1800s"`, `alert_strategy[0].notification_prompts == ["OPENED"]`.
  - `run "rejects_quote_in_text"`: `ready_text = "a\"b"`, `expect_failures = [var.ready_text]`.
  - `run "rejects_empty_resource_filter"`: `resource_filter = ""`, `expect_failures = [var.resource_filter]`.

- [ ] **Step 2: Run the test to see it fail**

  Run: `cd infra/modules/scale-alerts && terraform init -backend=false && terraform test`
  Expected: FAIL (no configuration files yet).

- [ ] **Step 3: Implement the module.**
  - `versions.tf`: copy `infra/modules/vertex-model/versions.tf`.
  - `variables.tf`: the inputs above, each with a description. Validations: `ready_text` and `down_text` are not empty and have no `"`. `resource_filter` is not empty.
  - `main.tf`: `locals.events = { ready = { text = var.ready_text, subject = "🟢 ${var.title} is ready" }, down = { text = var.down_text, subject = "⚪ ${var.title} scaled to 0" } }`, and `locals.filters` built in the format of the Step 1 assertion. One `google_monitoring_alert_policy.this` with `for_each = local.events`, `project = var.project_id`, `display_name = "${var.title}: ${each.key}"`, `combiner = "OR"`, one `conditions` block with `condition_matched_log { filter = local.filters[each.key] }`, the `alert_strategy` values from Global Constraints, and `documentation { subject = each.value.subject, content = each.value.subject, mime_type = "text/markdown" }`. Add a 1-line comment: log-based alerts count instances, so a scale from 1 to 2 also sends "ready".
  - `outputs.tf`: `filters = local.filters`.

- [ ] **Step 4: Run the test to see it pass**

  Run: `terraform test` in `infra/modules/scale-alerts`, then `terraform fmt -recursive` from the repo root.
  Expected: `Success! 4 passed, 0 failed.`

- [ ] **Step 5: Commit**

  ```bash
  git add infra/modules/scale-alerts
  git commit -m "feat: scale-alerts module (log-based Slack alerts for ready and scale down)"
  ```

### Task 2: Slack channel in core and the `.env` wiring

**Files:**
- Create: `infra/core/notifications.tf`
- Modify: `infra/core/variables.tf`, `infra/core/outputs.tf`, `infra/core/tests/core.tftest.hcl`, `scripts/hcp-sync.py:41-49`, `.envrc`, `.env.example`

**Interfaces:**
- Consumes: nothing.
- Produces: `google_monitoring_notification_channel.slack` with `display_name = "models-slack"` (Task 6 finds it by this name). Core variables `slack_bot_token` (ephemeral, sensitive) and `slack_channel` (string).

- [ ] **Step 1: Write the failing test.** In `core.tftest.hcl`, add `slack_bot_token = "test"` and `slack_channel = "#models"` to the file `variables` block. Add:
  - `run "slack_channel_keeps_token_out_of_state"` (`command = plan`): `type == "slack"`, `display_name == "models-slack"`, `labels.channel_name == "#models"`, `sensitive_labels[0].auth_token == null`.
  - `run "rejects_channel_without_hash"`: `slack_channel = "models"`, `expect_failures = [var.slack_channel]`.

- [ ] **Step 2: Run the test to see it fail**

  Run: `cd infra/core && terraform init -backend=false && terraform test -filter=tests/core.tftest.hcl`
  Expected: FAIL (undeclared variables).

- [ ] **Step 3: Implement.**
  - `variables.tf`: `slack_bot_token` is a copy of the `hf_token` block with its own description ("Slack bot token (xoxb-...), scope chat:write. Write-only: not in state or plan."). `slack_channel` is a string. Its validation is `startswith(var.slack_channel, "#")`, with the message "slack_channel must start with #, for example #models."
  - `notifications.tf`: `google_monitoring_notification_channel.slack` with `project = var.project_id`, `type = "slack"`, `display_name = "models-slack"`, `labels = { channel_name = var.slack_channel }`, `sensitive_labels { auth_token_wo = var.slack_bot_token, auth_token_wo_version = 1 }`, `depends_on = [google_project_service.apis]`. Add the rotation comment from `weights_copy.tf` with the variable names changed. Add `monitoring.googleapis.com` to the API list in `main.tf` (it is not there today), and add it to the `enables_apis_needed_by_first_apply` test.
  - `outputs.tf`: `slack_channel_id = google_monitoring_notification_channel.slack.name`.
  - `scripts/hcp-sync.py`: add `"slack_bot_token": E("SLACK_BOT_TOKEN"), "slack_channel": E("SLACK_CHANNEL")` to the `custom-models-bootstrap` variables. Add `"slack_bot_token"` to `SENSITIVE`.
  - `.envrc`: add `tf_var slack_channel "${SLACK_CHANNEL:-}"` and `export TF_VAR_slack_bot_token="${SLACK_BOT_TOKEN:-}"`, each with a 1-line comment like the HF line.
  - `.env.example`: add a `# Slack (infra/core: scale notifications, see infra/README.md)` block with `SLACK_BOT_TOKEN=` and `SLACK_CHANNEL="#models"`. The quotes are necessary: without them, direnv reads `#` as a comment and the value is empty (seen on 2026-11-20).

- [ ] **Step 4: Run the tests to see them pass**

  Run: `terraform test` in `infra/core`, then `./scripts/hcp-sync.py --dry-run`.
  Expected: all core tests pass. The dry run lists `slack_bot_token` (sensitive) and `slack_channel` for `custom-models-bootstrap`, or skips them when they are empty in `.env`. It prints no values.

- [ ] **Step 5: Commit**

  ```bash
  git add infra/core scripts/hcp-sync.py .envrc .env.example
  git commit -m "feat: Slack notification channel in core (write-only token)"
  ```

### Task 3: Vertex AI container logs on

**Files:**
- Modify: `infra/modules/vertex-model/main.tf:24-41`, `infra/modules/vertex-model/tests/vertex_model.tftest.hcl`

**Interfaces:**
- Produces: `output.vertex.deployed_model.disableContainerLogging == false`. `scripts/vertex.py` sends it unchanged, because `drop_nulls` keeps `false`.

- [ ] **Step 1: Write the failing test.** In the `defaults_scale_to_zero_on_l4` run, add: `output.vertex.deployed_model.disableContainerLogging == false`, with the message "container logs must be on: the scale-alerts filters read them".
- [ ] **Step 2: Run the test to see it fail.** Run `terraform test` in `infra/modules/vertex-model`. Expected: FAIL on that assertion.
- [ ] **Step 3: Implement.** Add `disableContainerLogging = false` to `local.deployed_model`, with the comment "Vertex AI set it to true when it was not given; scale-alerts needs the logs."
- [ ] **Step 4: Run the test to see it pass.** Run `terraform test` in the module. Expected: PASS.
- [ ] **Step 5: Commit**

  ```bash
  git add infra/modules/vertex-model
  git commit -m "fix: turn on Vertex AI container logs"
  ```

### Task 4: Real log check on `llm-a` (first GPU run)

**Files:**
- Modify: `docs/specs/2026-11-19-scale-notifications-slack-design.md` ("The log lines" table and "Open points")

**Interfaces:**
- Consumes: Task 3 (`disableContainerLogging = false` in the `vertex` output).
- Produces: the real values for Task 6: `resource.type`, the payload field (`textPayload` or `jsonPayload.message`), the ready line and the shutdown line of a Vertex AI container. `llm-b` uses the same vLLM and uvicorn stack, so the same values apply to it.

Warning: Step 2 starts an L4 GPU (about $1.34 per hour) for about 20 to 30 minutes. The endpoint does not answer during the undeploy and deploy.

- [ ] **Step 1: Apply `llm-a`.** Run `direnv exec . terraform plan` in `deployments/llm-a-gemma4-12b-vllm`. Expected: only the `vertex` output changes (`disableContainerLogging`). Then run `direnv exec . terraform apply -auto-approve`.
- [ ] **Step 2: Redeploy.** Run `./scripts/vertex.py undeploy deployments/llm-a-gemma4-12b-vllm`, then `./scripts/vertex.py deploy deployments/llm-a-gemma4-12b-vllm`. Expected: `Deployed model ID: ...`. Then run `direnv exec . gcloud ai endpoints describe <endpoint_id> --region=us-central1 --format='value(deployedModels[0].disableContainerLogging)'`. Expected: empty or `False`.
- [ ] **Step 3: Read the ready line.** The deploy starts 1 replica (`initialReplicaCount = 1`), so no test call is needed. Run `direnv exec . gcloud logging read 'resource.labels.endpoint_id="<endpoint_id>" AND ("Application startup complete" OR "Shutting down" OR "shutdown complete")' --freshness=1h --limit=20 --format=json`. Expected: an entry with `Application startup complete.`. Record `resource.type`, `logName` and the payload field.
- [ ] **Step 4: Read the shutdown line.** Wait 10 minutes after the ready line (300 s idle time, then the scale down). Run the Step 3 command again. Expected: an entry with `Application shutdown complete.` from the same resource. If no line comes, record what Vertex AI writes at scale down (for example in `prediction_deployment_observability`).
- [ ] **Step 5: Update the spec and commit.** Put the real values in the spec table. Close the open point. If a value differs from the Task 6 table, change that table in this plan now.

  ```bash
  git add docs/specs
  git commit -m "docs: real Vertex AI log lines for scale alerts"
  ```

### Task 5: `llm-b` prints `engine ready`

**Files:**
- Modify: `deployments/llm-b-qwen35-9b-fastapi/image/app.py` (`load_engine`), `variables.tf` (`image_tag` default), `image/cloudbuild.yaml` (`_TAG` default and comment), `README.md:36-40`, `tests/deployment.tftest.hcl` (image URI assertion)

**Interfaces:**
- Produces: the log line `engine ready` on stdout, after `AsyncLLM.from_engine_args` returns. Image tag `0.1.1`.

- [ ] **Step 1: Write the failing test.** In `deployment.tftest.hcl`, change the expected `imageUri` to end with `:0.1.1`.
- [ ] **Step 2: Run the test to see it fail.** Run `terraform test` in the deployment. Expected: FAIL on the image URI.
- [ ] **Step 3: Implement.** In `load_engine`, after the `engine = ...` line, add `print("engine ready", flush=True)`. Add the comment "scale-alerts reads this line: uvicorn starts before the model loads". Change `0.1.0` to `0.1.1` in `variables.tf`, `cloudbuild.yaml` and the README build command.
- [ ] **Step 4: Run the test to see it pass.** Run `terraform test`, then `python3 -m py_compile deployments/llm-b-qwen35-9b-fastapi/image/app.py`. Expected: PASS, and no compile error.
- [ ] **Step 5: Commit**

  ```bash
  git add deployments/llm-b-qwen35-9b-fastapi
  git commit -m "feat(llm-b): log engine ready after the model loads (image 0.1.1)"
  ```

### Task 6: Call `scale-alerts` in the 3 deployments

**Files:**
- Create: `deployments/tts-a-kokoro-cpu/alerts.tf`, `deployments/llm-a-gemma4-12b-vllm/alerts.tf`, `deployments/llm-b-qwen35-9b-fastapi/alerts.tf`
- Test: `tests/alerts.tftest.hcl` in each of the 3 deployments

**Interfaces:**
- Consumes: the Task 1 module and its `filters` output, and the Task 2 display name `models-slack`. `module.service.service_name` (model-service) and `module.model.endpoint_id` (vertex-model).
- Produces: `module.scale_alerts` in each root.

Each `alerts.tf` has this content:
- `data "google_monitoring_notification_channel" "slack" { display_name = "models-slack" }`, with the comment "Created by infra/core/notifications.tf. Apply core first."
- `module "scale_alerts"` with `source = "../../infra/modules/scale-alerts"`, `project_id = var.project_id`, `notification_channel = data.google_monitoring_notification_channel.slack.name`, and these values:

| Root | `title` | `resource_filter` | `ready_text` |
|---|---|---|---|
| `tts-a-kokoro-cpu` | `"TTS-A Kokoro"` | `resource.type="cloud_run_revision" AND resource.labels.service_name="${module.service.service_name}"` | `"STARTUP HTTP probe succeeded"` |
| `llm-a-gemma4-12b-vllm` | `"LLM-A Gemma 4 12B"` | `resource.type="aiplatform.googleapis.com/Endpoint" AND resource.labels.endpoint_id="${module.model.endpoint_id}"` | `"Application startup complete."` |
| `llm-b-qwen35-9b-fastapi` | `"LLM-B Qwen3.5 9B"` | same as llm-a | `"engine ready"` |

- [ ] **Step 1: Write the failing tests.** Copy the `mock_provider` and `variables` header from the root's `gateway.tftest.hcl`. Add one `run "alerts_watch_own_model"` (`command = apply`) with `override_data { target = data.google_monitoring_notification_channel.slack, values = { name = "projects/p/notificationChannels/1" } }`. Assertions:
  - TTS: `strcontains(module.scale_alerts.filters.ready, "service_name=\"tts-a-kokoro-cpu\"")` and `strcontains(module.scale_alerts.filters.ready, "STARTUP HTTP probe succeeded")`.
  - LLM-A and LLM-B: `strcontains(module.scale_alerts.filters.ready, "endpoint_id=\"${module.model.endpoint_id}\"")`, and the ready text from the table.
  - All 3: `strcontains(module.scale_alerts.filters.down, "Application shutdown complete.")`.
- [ ] **Step 2: Run the tests to see them fail.** Run `terraform init -backend=false && terraform test -filter=tests/alerts.tftest.hcl` in each root. Expected: FAIL (no `module.scale_alerts`).
- [ ] **Step 3: Implement** the 3 `alerts.tf` files from the table.
- [ ] **Step 4: Run the full check.** Run `./scripts/check.py` from the repo root. Expected: fmt, validate, test and tflint are OK in every root, including `infra/modules/scale-alerts`.
- [ ] **Step 5: Commit**

  ```bash
  git add deployments/*/alerts.tf deployments/*/tests/alerts.tftest.hcl
  git commit -m "feat: Slack scale alerts for tts-a, llm-a and llm-b"
  ```

### Task 7: Docs

**Files:**
- Modify: `infra/README.md` (core list in "What core creates", a new section "Scale notifications (Slack)" before "## Tests"), `CLAUDE.md` (module list, secrets table), `README.md` (one link in the setup part), the 3 deployment READMEs (rollout and check steps)

- [ ] **Step 1:** In `infra/README.md`, add the new section. It holds:
  - The Mermaid flowchart from the spec. Use the `diagrams` skill, including the render check.
  - The one-time Slack setup steps 1 to 5 from the spec.
  - The module inputs table and the limits list from the spec.
  - The rotation step: change `SLACK_BOT_TOKEN`, raise `auth_token_wo_version`, run `hcp-sync.py`, apply core.
  - "Send test notification" in the console as the first check.
- [ ] **Step 2:** In `CLAUDE.md`, add `infra/modules/scale-alerts/` to the module list. Add `SLACK_BOT_TOKEN` and `SLACK_CHANNEL` to the secrets table. In the root `README.md`, add a link to the new section.
- [ ] **Step 3:** In each deployment README, add a step after apply or deploy: "Wait for the Slack message `🟢 <title> is ready`. After the idle time, wait for `⚪ <title> scaled to 0`." Give the real times: Cloud Run about 15 min, Vertex AI 300 s idle plus shutdown. In both LLM READMEs, add the one-time redeploy: `./scripts/vertex.py undeploy deployments/<name>`, then `deploy`, because the deploy reuses the deployed model and does not change it. In the `llm-b` README, the build step uses tag `0.1.1`.
- [ ] **Step 4:** Run `./scripts/check.py`. Expected: OK. Check that no command is in two files (CLAUDE.md "Where docs go").
- [ ] **Step 5: Commit**

  ```bash
  git add README.md CLAUDE.md infra/README.md deployments/*/README.md docs
  git commit -m "docs: Slack scale notifications"
  ```

### Task 8: Rollout

**Files:**
- Modify (only if a check fails): the root that failed.

Warning: Step 3 and Step 5 start an L4 GPU (about $1.34 per hour) until each LLM scales down.

- [ ] **Step 1: Sync and apply core.** Run `./scripts/hcp-sync.py --dry-run`, then `./scripts/hcp-sync.py`. In `infra/core`, run `direnv exec . terraform plan`. Expected: the new API, the Slack channel and the new output only. Then run `direnv exec . terraform apply -auto-approve`.
- [ ] **Step 2 (user):** In the console, open Monitoring > Alerting > Edit notification channels. Click "Send test notification" on `models-slack`. Expected: a message in the Slack channel and on the phone. If it does not come, check that the bot is in the channel.
- [ ] **Step 3: Build and redeploy `llm-b`.** Run the build command from the `llm-b` README with tag `0.1.1`. Apply `deployments/llm-b-qwen35-9b-fastapi` (plan first). Then run `vertex.py undeploy`, then `deploy`.
- [ ] **Step 4: Apply the 3 deployments.** For each root, run `direnv exec . terraform plan`. Expected: 2 new alert policies and no other change. Then run `direnv exec . terraform apply -auto-approve`. Expected: no error from the data source (core is applied).
- [ ] **Step 5: Real check.** The `llm-b` deploy in Step 3 ran before its alerts existed, so it sends nothing. Make one cold start for each model: one call from the UI, or the test call from its README. Expected: one `🟢` message for each model. After the idle time (Cloud Run about 15 min, Vertex AI 300 s plus shutdown), expect one `⚪` message. If `llm-b` sends no `🟢`, read its logs for `engine ready` (Task 4 Step 3 command).
- [ ] **Step 6: Record and commit.** Write the real delay from log line to phone in the new `infra/README.md` section (spec limit 4).

  ```bash
  git add infra/README.md
  git commit -m "docs: measured Slack alert delay"
  ```
