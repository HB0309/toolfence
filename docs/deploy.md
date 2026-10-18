# ToolFence Dashboard — IBM Cloud Code Engine Deploy

> **IMPORTANT: Do NOT set `OPENROUTER_API_KEY` or any secret in the Code Engine
> application. The dashboard serves only pre-committed JSON from `results/` — no
> model calls are made at runtime.**

---

## 1. Prerequisites

| Tool | Version | Check |
|---|---|---|
| `ibmcloud` CLI | any recent | `ibmcloud version` |
| Code Engine plugin | any recent | `ibmcloud plugin list` |
| Python | 3.12 | `python --version` |
| Docker (or `podman`) | any recent | `docker version` |

Install the Code Engine plugin if not already present:

```bash
ibmcloud plugin install code-engine
```

Log in to IBM Cloud:

```bash
ibmcloud login --apikey <YOUR_IBM_CLOUD_API_KEY> -r us-south
```

Target your Code Engine project (create one if needed):

```bash
ibmcloud ce project create --name toolfence   # first time only
ibmcloud ce project select --name toolfence
```

---

## 2. Deploy from source (one command)

The repo root contains a `Dockerfile` that builds and runs the read-only dashboard. Code
Engine's build-from-source feature clones the repo, runs the Dockerfile, and deploys in a
single command — no separate image registry or push step required.

```bash
ibmcloud ce application create \
  --name toolfence-dashboard \
  --build-source https://github.com/<YOUR_ORG>/toolfence \
  --strategy dockerfile \
  --port 8080 \
  --min-scale 0 \
  --cpu 0.25 \
  --memory 0.5G
```

> **Note:** `--min-scale 0` enables serverless scaling — the app scales to zero when not in
> use, keeping costs at zero for idle time.
>
> **Do NOT add `--env OPENROUTER_API_KEY=...` or any other secret.** The dashboard reads
> only pre-committed JSON files from `results/` — it makes no outbound calls to model
> providers or any external service.
>
> Replace `<YOUR_ORG>` with your GitHub organisation or username. For a private repo, add
> `--build-git-token <GITHUB_PAT>` (a read-only token is sufficient).

---

## 4. Update the application

After rebuilding and pushing a new image:

```bash
ibmcloud ce application update \
  --name toolfence-dashboard \
  --image us.icr.io/<YOUR_NAMESPACE>/toolfence-dashboard:latest
```

To update results data, rebuild the image with the updated `results/` directory committed to
the repo, then run the update command above.

> **Do NOT add `--env OPENROUTER_API_KEY=...` or any other secret during update either.**
> The `must NOT` constraint applies to every `application create` and `application update`
> invocation.

---

## 5. Verify the deployment

Retrieve the application URL:

```bash
ibmcloud ce application get --name toolfence-dashboard --output url
```

Export it for the smoke test:

```bash
export TOOLFENCE_DEPLOY_URL=$(ibmcloud ce application get --name toolfence-dashboard --output url)
```

Run the smoke test:

```bash
pytest tests/test_deploy_smoke.py
```

Or skip network tests in a CI environment without the deployed URL:

```bash
pytest tests/test_deploy_smoke.py --skip-network
```

---

## 6. Security checklist

- [ ] `OPENROUTER_API_KEY` is **not** set in the Code Engine application environment
- [ ] `TELEGRAM_BOT_TOKEN` is **not** set in the Code Engine application environment
- [ ] `TELEGRAM_USER_ID` is **not** set in the Code Engine application environment
- [ ] No `.env` file is baked into the container image (verify with `docker inspect`)
- [ ] `results/` contains only pre-committed synthetic evaluation data — no live PII

---

## 7. Tear down

```bash
ibmcloud ce application delete --name toolfence-dashboard --force
```
