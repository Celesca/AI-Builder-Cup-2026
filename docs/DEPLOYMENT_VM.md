# Deploying VALZ on one VM with Firebase

The smallest Google Cloud footprint for VALZ: **one Compute Engine VM** running the Docker Compose stack that already exists in this
repository, and **Firebase** (Firestore and Authentication) for shared state and sign-in. The full managed design, with about 35
services, is in [DEPLOYMENT.md](DEPLOYMENT.md); this guide is the lean alternative for a hackathon, a pilot or a single plant.

![VALZ on one VM with Firebase](../images/system_architecture_minimal.png)

## What you get

Two parts, and the first one runs the code as it is today.

| Part | What it adds | Code changes |
|---|---|---|
| **A. VM** | The whole system on one Compute Engine VM, HTTPS by Caddy, the same OpenRouter and ElevenLabs calls as local development | **None** |
| **B. Firebase** | Firestore for decisions and run state shared across devices, Firebase Authentication (Google sign-in) | **Yes**: sign-in and Firestore access in the dashboard's server code (listed in B5) |

Google products used: **Compute Engine** (VM, disk, static IP, firewall, snapshots), **Firestore**, **Firebase Authentication** and **IAM**
(one service account). Everything else stays where it is today: OpenRouter for the vision model and the Gemba Kaizen LLM
(it can route to Gemini models), ElevenLabs for speech, Let's Encrypt for the certificate.

| Concern | Full guide ([DEPLOYMENT.md](DEPLOYMENT.md)) | This guide |
|---|---|---|
| Hosting | Cloud Run, load balancer, Cloud CDN, Cloud Armor, IAP, Cloud DNS | One VM, Caddy, your own DNS |
| Models and speech | Vertex AI Gemini, Speech-to-Text, Text-to-Speech, Video Intelligence, Transcoder | Unchanged (OpenRouter, ElevenLabs, YOLO on the VM) |
| Pipeline | Eventarc, Workflows, Pub/Sub, Cloud Tasks | The FastAPI process |
| State | Firestore, Cloud Storage, BigQuery | Firestore only; clips and the voice cache stay on the VM disk |
| Sign-in | IAP | Firebase Authentication |
| Delivery | Cloud Build, Artifact Registry, Cloud Deploy | `docker compose up --build` on the VM |
| Operations | Cloud Logging, Monitoring, Trace, budgets | `docker compose logs`, disk snapshots |

**Limits of one VM.** No autoscaling and no failover: a VM restart or a zone outage takes the site down until it comes back. Two
analyses at once share two vCPUs (the vision model and the LLM run on OpenRouter, so the load is mostly I/O plus YOLO and ffmpeg).
Uploads pass through the VM, so clips are limited by `MAX_VIDEO_MB` (500) and the VM's network. Move to the full guide when you need
more than that.

> **Read this first**
>
> - The `gcloud` and `firebase` commands were written against the documentation and **have not been run against a live project**. Use `--help` when a flag is rejected.
> - The two-host configuration below has been built and deployed on the current VM. Compose, Caddy and nginx configurations were validated, and HTTPS, CORS and browser navigation were checked.
> - **Part A has no sign-in.** Until Part B exists, anyone with the URL can run analyses and spend your model credits. Protect both the dashboard and the API before wider use.

## This VM: frontend and API on separate domains

The production Compose override serves **both applications on this VM**, using two virtual hosts:

| Address | Service |
|---|---|
| `https://valz.limitlesstech-co.com` | SvelteKit dashboard |
| `https://gemba.limitlesstech-co.com` | FastAPI (for example `/health`, `/docs`, `/analysis/analyze/upload`) |
| `https://gemba.limitlesstech-co.com/api/*` | Compatibility alias for older clients; `/api` is stripped |

Both DNS A records point to `157.254.192.65`. [deploy/Caddyfile](../deploy/Caddyfile) handles HTTPS and automatic certificate
renewal for both hosts. [deploy/nginx.conf](../deploy/nginx.conf) provides the corresponding HTTP virtual hosts for the base
Compose stack; **do not run nginx and Caddy on port 80 at the same time**.

On this VM the checkout is `/home/celescadev/AI-Builder-Cup-2026`. Its untracked `.env` contains:

```dotenv
DOMAIN=valz.limitlesstech-co.com
API_DOMAIN=gemba.limitlesstech-co.com
COMPOSE_PROJECT_NAME=ai_backend
```

The project name preserves the existing Caddy certificate volumes. Deploy **from this checkout**, not the old
`/home/celescadev/U-HACKATHON26/ai_backend` checkout. The old credentials were copied locally to `ai_backend/.env` (mode `600`);
no credentials are committed. API cache and voice data use named volumes, and all three services restart automatically.

```bash
cd /home/celescadev/AI-Builder-Cup-2026
sudo docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build --wait
sudo docker compose -f docker-compose.yml -f docker-compose.https.yml ps
sudo docker compose -f docker-compose.yml -f docker-compose.https.yml logs --tail=100 api frontend caddy
```

For a fresh VM, copy `.env.example` to `.env`, copy `ai_backend/.env.example` to `ai_backend/.env`, configure model keys,
then start the same Compose command. A fresh install does not need `COMPOSE_PROJECT_NAME=ai_backend`.

The override sets the frontend's `AI_BACKEND_URL=https://gemba.limitlesstech-co.com` and its public `ORIGIN`. The existing
`/config` endpoint supplies the API address to the browser, so status, analysis, voice and video uploads use the HTTPS API
host directly. FastAPI's `ALLOWED_ORIGINS` allows `https://valz.limitlesstech-co.com`; the frontend `/api/*` proxy is retained
as a same-origin fallback. `ALLOW_BACKEND_OVERRIDE=false` prevents arbitrary server-side proxy destinations.

```bash
curl -fsS https://valz.limitlesstech-co.com/config  # uploadBackend = https://gemba.limitlesstech-co.com
curl -fsS https://gemba.limitlesstech-co.com/health
curl -fsS https://valz.limitlesstech-co.com/api/health
```

**Security:** the current deployment has no sign-in. CORS is not authentication; a public API caller can spend model credits.
Before sharing beyond the pilot, add authentication to **both hosts** (or an API authorization layer), not just the dashboard.

The generic Google Cloud provisioning instructions follow below. Where they use `$DOMAIN`, it is the frontend domain;
create an additional DNS record for `$API_DOMAIN` and include `API_DOMAIN` in `.env` too.

## Variables

```bash
export PROJECT_ID=valz-prod                  # globally unique
export BILLING_ACCOUNT=<XXXXXX-XXXXXX-XXXXXX>
export REGION=asia-southeast1
export ZONE=asia-southeast1-b
export DOMAIN=valz.<your-domain>
export API_DOMAIN=gemba.<your-domain>
sa() { echo "valz-vm@$PROJECT_ID.iam.gserviceaccount.com"; }
```

---

# Part A: the VM

## A0. Project, billing and API

```bash
gcloud auth login
gcloud projects create $PROJECT_ID --name="VALZ"
gcloud billing projects link $PROJECT_ID --billing-account=$BILLING_ACCOUNT
gcloud config set project $PROJECT_ID
gcloud services enable compute.googleapis.com
```

## A1. Static IP and firewall

The IP must not change, because DNS points at it. The firewall opens only what Caddy needs.

```bash
gcloud compute addresses create valz-ip --region=$REGION
export IP=$(gcloud compute addresses describe valz-ip --region=$REGION --format='value(address)')
export MY_IP=$(curl -s https://api.ipify.org)

gcloud compute firewall-rules create valz-web --network=default \
  --allow=tcp:80,tcp:443,udp:443 --target-tags=valz --source-ranges=0.0.0.0/0
gcloud compute firewall-rules create valz-ssh --network=default \
  --allow=tcp:22 --target-tags=valz --source-ranges=$MY_IP/32

# The default network ships rules that let anyone try SSH and RDP on every VM
gcloud compute firewall-rules delete default-allow-ssh default-allow-rdp --quiet || true
```

Do not restrict `valz-web` to your plant's addresses: Let's Encrypt validates the certificate from the open Internet and would fail. Use the
password in A5 (and sign-in in part B) instead.

## A2. The VM

```bash
gcloud iam service-accounts create valz-vm --display-name="VALZ VM"

gcloud compute instances create valz-vm --zone=$ZONE \
  --machine-type=e2-standard-2 \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=60GB --boot-disk-type=pd-balanced \
  --address=valz-ip --tags=valz \
  --service-account=$(sa) --scopes=cloud-platform \
  --metadata=enable-oslogin=TRUE \
  --metadata-from-file=startup-script=deploy/vm-startup.sh
```

`e2-standard-2` (2 vCPU, 8 GB) is comfortable; `e2-medium` (4 GB) is the smallest that fits (the backend idles under 1 GB, but the image
build and YOLO need headroom). The 60 GB disk holds the images (PyTorch is large), the Hugging Face cache, uploaded clips and the
certificate. The service account has no roles yet; part B grants the one it needs. `--scopes=cloud-platform` only opens the door; IAM roles
decide what the account may do.

**Check:** wait two minutes for the startup script, then

```bash
gcloud compute ssh valz-vm --zone=$ZONE --command='docker --version && docker compose version'
# if it fails: gcloud compute instances get-serial-port-output valz-vm --zone=$ZONE | tail -30
```

## A3. DNS

At your DNS provider, create `A` records for both `$DOMAIN` and `$API_DOMAIN` pointing to `$IP`. Cloud DNS is not needed.

**Check:** `dig +short $DOMAIN` prints `$IP`. Do this before A6, or the certificate request fails and Caddy backs off for a while.

## A4. Put the code on the VM

If the repository is on GitHub, clone it on the VM. Otherwise send the working tree from the repository root:

```bash
tar --exclude=node_modules --exclude=.git --exclude=.venv --exclude=.svelte-kit --exclude=build \
    -czf - . | gcloud compute ssh valz-vm --zone=$ZONE --command='mkdir -p ~/valz && tar -xzf - -C ~/valz'
```

## A5. Configure

```bash
gcloud compute ssh valz-vm --zone=$ZONE
cd ~/valz
printf 'DOMAIN=%s\nAPI_DOMAIN=%s\n' "$DOMAIN" "$API_DOMAIN" > .env  # read by docker compose
cp ai_backend/.env.example ai_backend/.env
nano ai_backend/.env                                    # OPENROUTER_API_KEY, optional ELEVENLABS_API_KEY
chmod 600 ai_backend/.env .env
```

The model keys live in this file on the VM's disk, which Google encrypts at rest. The file is the one place the secrets exist, so do not
copy it into the repository.

**Protect access before wider use.** The current two-host deployment has no authentication. A password on only the
frontend does not protect the public API. Prefer application/API authentication that supports the browser's cross-origin
requests. Caddy `basic_auth` on both hosts also requires credential forwarding and CORS preflight handling; simply adding
a password block is not enough for the current direct browser API calls. Part B's frontend-only session checks must likewise
be extended to protect the API host.

## A6. Start

```bash
cd ~/valz
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

[docker-compose.https.yml](../docker-compose.https.yml) swaps nginx for Caddy and sets `ALLOW_BACKEND_OVERRIDE=false`, so the UI cannot
point the proxy at an address a visitor types. The first build takes several minutes (CPU PyTorch wheels, the spaCy model and the YOLO weights are
baked into the image). Compose restarts the containers after a reboot, and the startup script keeps Docker enabled.

## A7. Check

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml ps          # api, frontend, caddy are Up
docker compose -f docker-compose.yml -f docker-compose.https.yml logs caddy | grep -i "certificate obtained"
curl -fsS https://$API_DOMAIN/health                                      # "status":"healthy"
curl -fsS https://$DOMAIN/api/health                                      # frontend proxy fallback
```

In the browser: `https://$DOMAIN` loads the dashboard, the cached demo clip plays, and uploading a clip returns
cards (needs `OPENROUTER_API_KEY`). `https://$API_DOMAIN/docs` shows the API documentation.

**Request path**: the browser reaches Caddy, which sends the frontend host to SvelteKit and the API host to FastAPI.
The dashboard reads `/config` and calls the public API host directly (CORS permits the frontend origin). The frontend's
`/api/*` proxy remains a fallback; FastAPI calls OpenRouter and ElevenLabs. Numbers 4 and 5 in the diagram appear in part B.

## A8. Operate

```bash
# Deploy a new version: send the code again (A4), then
cd ~/valz && docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build

# Logs and health
docker compose -f docker-compose.yml -f docker-compose.https.yml logs -f --tail=100 api
docker stats --no-stream; df -h /

# Reclaim disk after many rebuilds (removes unused images)
docker image prune -af
```

**Backup.** The VM disk holds the voice cache, the certificate and (until part B) nothing that cannot be rebuilt. Snapshot it daily:

```bash
gcloud compute resource-policies create snapshot-schedule valz-daily --region=$REGION \
  --max-retention-days=7 --on-source-disk-delete=keep-auto-snapshots --daily-schedule --start-time=20:00
gcloud compute disks add-resource-policies valz-vm --zone=$ZONE --resource-policies=valz-daily
```

(`20:00` is UTC, which is 03:00 in Bangkok.)

**Resize.** `gcloud compute instances stop valz-vm --zone=$ZONE`, then
`gcloud compute instances set-machine-type valz-vm --zone=$ZONE --machine-type=e2-standard-4`, then `start`. The IP and disk stay.

---

# Part B: Firebase

A Firebase project is a Google Cloud project with Firebase turned on, so this uses the project from part A. **Firestore here is the same
database service the full guide uses**, so moving to the managed design later needs no data migration.

## B1. Turn on Firebase and create the database

```bash
gcloud services enable firestore.googleapis.com firebase.googleapis.com identitytoolkit.googleapis.com
npm install -g firebase-tools
firebase login
firebase projects:addfirebase $PROJECT_ID
gcloud firestore databases create --location=$REGION --type=firestore-native
```

The database location cannot be changed later.

## B2. Rules, indexes, backups and expiry

[deploy/firebase/](../deploy/firebase) holds the rules (deny everything to clients; the dashboard's server uses the Admin SDK, which bypasses them),
one index and `firebase.json`.

```bash
(cd deploy/firebase && firebase deploy --only firestore --project $PROJECT_ID)

gcloud firestore backups schedules create --database='(default)' --recurrence=daily --retention=7d
gcloud firestore fields ttls update expireAt --collection-group=runs --enable-ttl
```

The browser never connects to Firestore, so there is no client-side security to get wrong.
**Check:** `firebase firestore:indexes --project $PROJECT_ID` lists the `cards` index; the rules page in the Firebase console shows deny-all.

## B3. Let the VM use Firestore, with no key file

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$(sa)" \
  --role=roles/datastore.user --condition=None
# Only if the dashboard issues Firebase session cookies (B5): lets the Admin SDK create and verify them
gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$(sa)" \
  --role=roles/firebaseauth.admin --condition=None
```

On a Compute Engine VM, Application Default Credentials come from the attached service account through the metadata server, so
`firebase-admin` needs no JSON key. Inside a Docker container on the VM the same metadata server is reachable, so the containers inherit it.

## B4. Sign-in

In the Firebase console:

1. **Authentication → Get started → Sign-in method → Google → Enable**, and pick a support email.
2. **Authentication → Settings → Authorized domains → Add** `$DOMAIN`.
3. Register a web app and read its config (the `apiKey` of a Firebase web app is an identifier, not a secret):

```bash
firebase apps:create web valz --project $PROJECT_ID
firebase apps:sdkconfig web <APP_ID> --project $PROJECT_ID
```

Who may sign in is a list of email addresses in an environment variable (`ALLOWED_EMAILS`), checked on the server after the token is
verified. A Google account that is not on the list gets a 403.

## B5. What the code must do

None of this is in the repository yet. It is the work that turns part A into part B:

- **Sign-in.** A `/login` page with the Firebase web SDK (`signInWithPopup`, Google provider). It posts the ID token to the server, which verifies it with `firebase-admin`, checks `email_verified` and `ALLOWED_EMAILS`, and sets a session cookie (`createSessionCookie`). `hooks.server.ts` rejects every page and every `/api/*` call without a valid cookie, which also protects your OpenRouter spend.
- **Firestore access, server side only.** `initializeApp()` with no credentials (they come from the VM). Server routes read and write the collections below; the Svelte stores that keep decisions and marks in `localStorage` (`valz-run-v1`, `valz-marks-v1`, `valz-rules-v1`) call them instead.
- **Data model** (the same as the full guide, minus the bucket fields):

```
runs/{run_id}                    status, source {name, station_name}, language, metrics, expireAt
runs/{run_id}/segments/{id}      class, start, end, confidence, status, resolved_by
runs/{run_id}/cards/{id}         the action card + decision, decidedBy, decidedAt
runs/{run_id}/questions/{id}     question, answer, rootCause
rules/{rule_id}                  the safety rules shared by all managers
```

- **The backend does not change.** `ai_backend` stays stateless apart from the voice-audio cache, which remains a SQLite file in the `voice-data` volume on the VM.

Environment for the `frontend` service (add to a Compose override or to `docker-compose.https.yml`): `FIREBASE_PROJECT_ID`, `ALLOWED_EMAILS`
(comma-separated), and the web config values from B4 as public variables.

## B6. Check

1. An unauthenticated request to `https://$DOMAIN` redirects to the sign-in page; `/api/health` without a cookie returns 401.
2. A Google account on `ALLOWED_EMAILS` reaches the dashboard; one that is not gets 403.
3. Approve a card, then open the dashboard in a second browser signed in as another manager: the decision is there. The Firestore console shows `runs/<run_id>/cards/<id>` with the decision.
4. Remove the Caddy `basic_auth` block (sign-in replaces it) and run `docker compose … up -d`.

---

## Tear down

```bash
gcloud compute instances delete valz-vm --zone=$ZONE --quiet
gcloud compute addresses delete valz-ip --region=$REGION --quiet           # an unused static IP is billed
gcloud compute firewall-rules delete valz-web valz-ssh --quiet
gcloud compute resource-policies delete valz-daily --region=$REGION --quiet
gcloud firestore databases delete --database='(default)'                   # part B only
# or remove everything at once:
gcloud projects delete $PROJECT_ID
```

Snapshots are kept after the VM is deleted (`keep-auto-snapshots`); delete them with `gcloud compute snapshots list` and `delete`.

## Cost

The fixed costs are the VM, its boot disk, the snapshots and the static IP (billed whether or not the VM runs). Model and speech
calls are billed by OpenRouter and ElevenLabs, not by Google. Firestore has a free daily quota that a single plant usually stays
inside; check the Firestore pricing page for the current limits. Set a budget alert on the billing account:

```bash
gcloud services enable billingbudgets.googleapis.com
gcloud billing budgets create --billing-account=$BILLING_ACCOUNT --display-name="VALZ" \
  --budget-amount=100USD --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
```

## Moving up to the full design

Nothing here is a dead end. Firestore and its data model carry over unchanged. Caddy is replaced by the load balancer, the Compose stack by
two Cloud Run services (the same images), and OpenRouter and ElevenLabs by Vertex AI and Google speech, one swap at a time. The order is in
[DEPLOYMENT.md](DEPLOYMENT.md) and the code swaps are in [What changes in the code](system_architecture.html#code-changes).
