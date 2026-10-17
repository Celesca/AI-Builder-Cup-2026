# Deploying VALZ on Google Cloud

This guide deploys the whole system from an empty Google Cloud project, one service at a time, in dependency order.
Each section says what the service does for VALZ, which tool deploys it, the commands, and how to check it worked.
The architecture is in [system_architecture.html](system_architecture.html).

> **Read this first**
>
> - The commands were written against the Google Cloud documentation and **have not been run against a live project**. Run `gcloud <command> --help` when a flag is rejected; Google renames flags and moves features between preview and GA.
> - Model IDs, voice names and regional availability change. Check the Gemini, Speech-to-Text (Chirp 3), Text-to-Speech, Transcoder and RAG Engine location tables before you pick regions.
> - The repository's code still calls OpenRouter and ElevenLabs (see [What changes in the code](system_architecture.html#code-changes)). Section 11 has an **interim path** that puts today's unchanged image on Cloud Run first, so you can deploy the platform before the code migration lands.

## Who deploys what

| Tool | Deploys | When |
|---|---|---|
| **Cloud Build** (trigger on `main`) | `valz-api`, `valz-frontend`, `valz-perception` images, then `gcloud run deploy` / `jobs deploy` | Every push; set up in §18 |
| **Cloud Deploy** (optional) | Promotes a release of a Cloud Run service from staging to production | After a Cloud Build run; §18 |
| **gcloud** (you, once) | Project, APIs, IAM, buckets, Firestore, Pub/Sub, KMS, secrets, Workflows, Eventarc, load balancer, DNS, Armor, IAP, Scheduler, Tasks, BigQuery, budgets | §0–§17, §19 |
| **A Python script** (you, once, then on change) | The Vertex AI RAG Engine corpus | §8 |
| **Google Cloud console** (you, once) | OAuth consent screen for IAP, GitHub connection for Cloud Build, the Looker Studio report | §15, §16, §18 |
| **Nothing to deploy** | Gemini, Video Intelligence, Transcoder, Text-to-Speech, Translation (managed APIs; you enable them and grant IAM) | §0, §1, §7, §9, §10 |

## Conventions

Run everything in one shell so the variables carry over. Replace the values in angle brackets.

```bash
export PROJECT_ID=valz-prod                 # globally unique
export BILLING_ACCOUNT=<XXXXXX-XXXXXX-XXXXXX>
export REGION=asia-southeast1               # Cloud Run, buckets, Firestore, Workflows (closest to Thai plants)
export VERTEX_LOCATION=global               # Gemini; set separately, model availability differs by location
export DOMAIN=valz.<your-domain>
export AR=$REGION-docker.pkg.dev/$PROJECT_ID/valz
export RAW=$PROJECT_ID-valz-raw
export PROCESSED=$PROJECT_ID-valz-processed
export STATIC=$PROJECT_ID-valz-static
sa() { echo "valz-$1@$PROJECT_ID.iam.gserviceaccount.com"; }   # sa api -> valz-api@...
```

Names used throughout: services `valz-api`, `valz-frontend`; job `valz-perception`; workflow `valz-pipeline`; Artifact Registry repository `valz`.

---

## 0. Project, billing and APIs

**What:** the container for everything. **Deployed by:** gcloud.

```bash
gcloud auth login
gcloud projects create $PROJECT_ID --name="VALZ"
gcloud billing projects link $PROJECT_ID --billing-account=$BILLING_ACCOUNT
gcloud config set project $PROJECT_ID
export PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  aiplatform.googleapis.com videointelligence.googleapis.com transcoder.googleapis.com \
  speech.googleapis.com texttospeech.googleapis.com translate.googleapis.com \
  firestore.googleapis.com pubsub.googleapis.com storage.googleapis.com \
  workflows.googleapis.com workflowexecutions.googleapis.com eventarc.googleapis.com \
  cloudtasks.googleapis.com cloudscheduler.googleapis.com bigquery.googleapis.com \
  secretmanager.googleapis.com cloudkms.googleapis.com iam.googleapis.com \
  iamcredentials.googleapis.com compute.googleapis.com dns.googleapis.com iap.googleapis.com \
  clouddeploy.googleapis.com logging.googleapis.com monitoring.googleapis.com \
  cloudtrace.googleapis.com clouderrorreporting.googleapis.com cloudresourcemanager.googleapis.com \
  billingbudgets.googleapis.com
```

**Check:** `gcloud services list --enabled | wc -l` shows the list above.
**Gotcha:** an organisation policy such as "Domain restricted sharing" blocks `allUsers` on the static bucket (§3) and `--allow-unauthenticated` on the frontend (§14). Ask the org admin for an exception on this project.

## 1. Service accounts and IAM

**What:** one identity per service, so no API key is needed anywhere. Gemini, Speech, Firestore and the buckets are all reached with the service account's credentials. **Deployed by:** gcloud.

```bash
for s in api perception pipeline frontend build scheduler pubsub; do
  gcloud iam service-accounts create valz-$s --display-name="VALZ $s"
done

grant() { gcloud projects add-iam-policy-binding $PROJECT_ID --member="serviceAccount:$(sa $1)" --role="$2" --condition=None --quiet >/dev/null; }

# valz-api: models, state, events, speech, translation, analytics, starting workflows
for r in aiplatform.user datastore.user pubsub.publisher cloudtranslate.user speech.client \
         serviceusage.serviceUsageConsumer bigquery.dataEditor bigquery.jobUser \
         workflows.invoker cloudtasks.enqueuer; do grant api roles/$r; done
# valz-perception: reads clips, writes keyframes, calls Video Intelligence
for r in storage.objectUser serviceusage.serviceUsageConsumer; do grant perception roles/$r; done
# valz-pipeline: runs the workflow and the Eventarc trigger
for r in run.developer run.invoker transcoder.admin workflows.invoker eventarc.eventReceiver \
         storage.objectUser logging.logWriter; do grant pipeline roles/$r; done
# valz-build: builds and deploys
for r in run.admin artifactregistry.writer logging.logWriter storage.objectViewer; do grant build roles/$r; done

# valz-api signs upload URLs as itself, through the IAM Credentials API
gcloud iam service-accounts add-iam-policy-binding $(sa api) \
  --member="serviceAccount:$(sa api)" --role=roles/iam.serviceAccountTokenCreator
# valz-build may deploy services that run as the other accounts
for s in api perception frontend; do
  gcloud iam service-accounts add-iam-policy-binding $(sa $s) \
    --member="serviceAccount:$(sa build)" --role=roles/iam.serviceAccountUser
done
# The Cloud Storage service agent must publish events for Eventarc
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$(gcloud storage service-agent --project=$PROJECT_ID)" \
  --role=roles/pubsub.publisher --condition=None
# Pub/Sub mints OIDC tokens for push delivery as valz-pubsub
gcloud iam service-accounts add-iam-policy-binding $(sa pubsub) \
  --member="serviceAccount:service-$PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role=roles/iam.serviceAccountTokenCreator
```

`valz-frontend`, `valz-scheduler` and `valz-pubsub` get only `run.invoker` on `valz-api`, granted in §11 once the service exists.
**Check:** `gcloud projects get-iam-policy $PROJECT_ID --flatten=bindings --filter="bindings.members:valz-api" --format="value(bindings.role)"` lists the roles above.
**Gotcha:** add people as `roles/viewer` plus the roles for the services they own; do not hand out `roles/owner` to the team.

## 2. Artifact Registry

**What:** the Docker repository the images are pushed to. **Deployed by:** gcloud.

```bash
gcloud artifacts repositories create valz --repository-format=docker --location=$REGION \
  --description="VALZ images"
gcloud auth configure-docker $REGION-docker.pkg.dev
```

**Check:** `gcloud artifacts repositories list --location=$REGION`.
**Gotcha:** add a cleanup policy later (keep the 10 newest tags) so old images do not accumulate.

## 3. Cloud Storage

**What:** three buckets. `raw-clips` takes the browser uploads, `processed` holds transcodes, keyframes, evidence snapshots and the voice-audio cache, `static` holds the demo clips served by the CDN. **Deployed by:** gcloud.

```bash
# Private buckets for footage: no public access, uniform IAM
for b in $RAW $PROCESSED; do
  gcloud storage buckets create gs://$b --location=$REGION \
    --uniform-bucket-level-access --public-access-prevention
done
# Public bucket for demo clips only (never real footage)
gcloud storage buckets create gs://$STATIC --location=$REGION --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding gs://$STATIC \
  --member=allUsers --role=roles/storage.objectViewer

cat > cors.json <<EOF
[{"origin": ["https://$DOMAIN"], "method": ["PUT", "POST", "GET", "HEAD"],
  "responseHeader": ["Content-Type", "x-goog-resumable"], "maxAgeSeconds": 3600}]
EOF
cat > lifecycle-raw.json <<EOF
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 30}}]}
EOF
cat > lifecycle-processed.json <<EOF
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": 90}}]}
EOF
gcloud storage buckets update gs://$RAW       --cors-file=cors.json --lifecycle-file=lifecycle-raw.json
gcloud storage buckets update gs://$PROCESSED --lifecycle-file=lifecycle-processed.json

# Who may touch what
gcloud storage buckets add-iam-policy-binding gs://$RAW --member="serviceAccount:$(sa api)" --role=roles/storage.objectCreator
gcloud storage buckets add-iam-policy-binding gs://$PROCESSED --member="serviceAccount:$(sa api)" --role=roles/storage.objectUser

# Demo clips for the CDN (same /demo/ path the frontend already uses)
gcloud storage rsync --recursive frontend/static/demo gs://$STATIC/demo
```

The lifecycle rules are the retention policy for CCTV: raw clips are deleted after 30 days, derived data after 90. Change them to your plant's rule.
**Check:** `gcloud storage ls` shows three buckets; `curl -I https://storage.googleapis.com/$STATIC/demo/<file>` returns 200; the same for `$RAW` returns 403.
**Why uploads go to a bucket:** Cloud Run rejects HTTP/1 request bodies over 32 MiB, and VALZ accepts clips up to 550 MB. The browser therefore uploads straight to `raw-clips` with a signed URL (see the upload contract in the architecture page).

## 4. Firestore

**What:** the state store (node 07): runs, segments, cards, decisions, questions and the voice cache index. **Deployed by:** gcloud.

```bash
gcloud firestore databases create --location=$REGION --type=firestore-native

# Runs expire after 90 days; the app writes an `expireAt` timestamp on each run
gcloud firestore fields ttls update expireAt --collection-group=runs --enable-ttl

# One example index: the dashboard lists cards by status, highest priority first
gcloud firestore indexes composite create --collection-group=cards \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=priority,order=descending
```

**Check:** `gcloud firestore databases list`.
**Gotcha:** the database location cannot be changed after creation. Customer-managed keys (§6) must be chosen when the database is created; if you need them for Firestore, do §6 first and check `gcloud firestore databases create --help` for the key flag.

## 5. Pub/Sub

**What:** three topics. `clip.uploaded` announces new clips (a record for subscribers; the workflow itself is started by Eventarc), `segment.uncertain` carries questions for the Voice Agent, `alert.raised` carries safety alerts. **Deployed by:** gcloud.

```bash
for t in clip.uploaded segment.uncertain alert.raised segment.uncertain.dlq; do
  gcloud pubsub topics create $t
done
```

The push subscriptions are created in §11, once `valz-api` has a URL.
**Check:** `gcloud pubsub topics list`.

## 6. Secret Manager and Cloud KMS

**What:** the few secrets that remain (the GCP version has no model or speech API keys), and a customer-managed encryption key for the footage buckets. **Deployed by:** gcloud.

```bash
# Secret Manager: example secret; add the IAP OAuth client secret here too (§15)
printf '%s' '<https://hooks.example.com/...>' | gcloud secrets create valz-alert-webhook --data-file=-
gcloud secrets add-iam-policy-binding valz-alert-webhook \
  --member="serviceAccount:$(sa api)" --role=roles/secretmanager.secretAccessor

# Cloud KMS: key for the footage buckets
gcloud kms keyrings create valz --location=$REGION
gcloud kms keys create footage --keyring=valz --location=$REGION --purpose=encryption
KEY=projects/$PROJECT_ID/locations/$REGION/keyRings/valz/cryptoKeys/footage
gcloud kms keys add-iam-policy-binding footage --keyring=valz --location=$REGION \
  --member="serviceAccount:$(gcloud storage service-agent --project=$PROJECT_ID)" \
  --role=roles/cloudkms.cryptoKeyEncrypterDecrypter
gcloud storage buckets update gs://$RAW gs://$PROCESSED --default-encryption-key=$KEY
```

**Check:** `gcloud secrets list`; `gcloud storage buckets describe gs://$RAW --format="value(default_kms_key)"`.
**Gotcha:** only new objects use the key. A destroyed key makes the data unreadable, which is the point, so restrict `cloudkms.admin`.

## 7. Vertex AI: Gemini

**What:** the vision model for the Safety Agent and the text model for the Gemba Kaizen and Voice agents. **Deployed by:** nothing; the API is enabled in §0 and `valz-api`'s `aiplatform.user` role is granted in §1.

Smoke test with your own account:

```bash
curl -s -X POST \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" \
  "https://aiplatform.googleapis.com/v1/projects/$PROJECT_ID/locations/global/publishers/google/models/gemini-2.5-flash:generateContent" \
  -d '{"contents":[{"role":"user","parts":[{"text":"Reply with the word OK"}]}]}'
```

In the application, use the `google-genai` SDK in Vertex mode, which reads credentials from the service account:

```python
from google import genai
client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
reply = client.models.generate_content(model="gemini-2.5-flash", contents="Reply with the word OK")
```

Environment variables for `valz-api` (set in §11): `GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `VLM_MODEL`, `LSS_LLM_MODEL`, `VOICE_LLM_MODEL`. Keyframes go in as inline images; a short clip can go in by `gs://` URI.
**Check:** the smoke test returns text. A `403` means the API is off or the role is missing; a `404` means the model ID is not offered in that location.
**Gotcha:** `gemini-2.5-flash` is an example. Pick the current Flash-class model from Model Garden for the vision step and a cheaper one for the card text, then set them in `VLM_MODEL` and `LSS_LLM_MODEL`. Watch the per-minute quota during rehearsals.

## 8. Vertex AI RAG Engine

**What:** retrieval over the countermeasure cards (and later plant SOPs and past approved cards) so the Gemba Kaizen Agent cites sources. **Deployed by:** a Python script you run once and again whenever the cards change.

```bash
pip install google-cloud-aiplatform
python - <<'EOF'
import json, os, pathlib, subprocess
cards = json.load(open("ai_backend/knowledge/lss_cards.json"))["cards"]
out = pathlib.Path("rag_docs"); out.mkdir(exist_ok=True)
for c in cards:   # one small text file per card retrieves better than one big JSON file
    (out / f"{c['id']}.md").write_text(
        f"# {c['id']}: {c.get('title','')}\n\n" + "\n".join(f"{k}: {v}" for k, v in c.items() if k != "id"))
subprocess.run(["gcloud", "storage", "rsync", "rag_docs", f"gs://{os.environ['PROCESSED']}/knowledge"], check=True)
EOF

python - <<'EOF'
import os, vertexai
from vertexai import rag
vertexai.init(project=os.environ["PROJECT_ID"], location="us-central1")   # use a location RAG Engine supports
corpus = rag.create_corpus(display_name="valz-knowledge")
rag.import_files(corpus.name, [f"gs://{os.environ['PROCESSED']}/knowledge"],
    transformation_config=rag.TransformationConfig(
        chunking_config=rag.ChunkingConfig(chunk_size=512, chunk_overlap=100)))
print(corpus.name)   # projects/…/locations/…/ragCorpora/…  -> RAG_CORPUS for valz-api
EOF
```

If the `cards` key differs in your copy of `lss_cards.json`, adjust the first script; the file is the source of truth.
**Check:**

```python
rag.retrieval_query(rag_resources=[rag.RagResource(rag_corpus=corpus.name)],
    text="operator reaches across the table to a bin",
    rag_retrieval_config=rag.RagRetrievalConfig(top_k=3))
```

should return the motion cards (`KC-MOT-*`).
**Gotcha:** RAG Engine is offered in fewer locations than Cloud Run; it can sit in a different location from `$REGION`. The SDK surface moves between releases, so check the current RAG Engine quickstart if an import fails.

## 9. Video Intelligence API and Transcoder API

**What:** Video Intelligence counts and tracks people (replacing YOLOv8) and finds shot changes; the Transcoder API turns any upload into an H.264 MP4 plus a browser preview (replacing ffmpeg in the API). **Deployed by:** nothing; both are enabled in §0. The workflow (§13) creates Transcoder jobs.

Smoke test, person detection (returns an operation to poll):

```bash
curl -s -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" \
  https://videointelligence.googleapis.com/v1/videos:annotate -d '{
    "inputUri": "gs://'$STATIC'/demo/<clip>.mp4",
    "features": ["PERSON_DETECTION"],
    "videoContext": {"personDetectionConfig": {"includeBoundingBoxes": true}}
  }'
# then: curl -H "Authorization: Bearer $(gcloud auth print-access-token)" https://videointelligence.googleapis.com/v1/<operation name>
```

Smoke test, Transcoder:

```bash
gcloud transcoder jobs create --location=$REGION \
  --input-uri=gs://$STATIC/demo/<clip>.mp4 --output-uri=gs://$PROCESSED/test/ --preset=preset/web-hd
gcloud transcoder jobs list --location=$REGION
```

**Check:** the person-detection operation ends with `done: true` and `personDetectionAnnotations`; the Transcoder job reaches `SUCCEEDED` and `gs://$PROCESSED/test/` holds an MP4.
**Gotchas:** if a Transcoder job fails with permission denied on a `gs://` path, the error names the identity it used; grant it `roles/storage.objectAdmin` on the bucket (the Transcoder service agent is `service-$PROJECT_NUMBER@gcp-sa-transcoder.iam.gserviceaccount.com`). Video Intelligence offers a few processing locations only; add `"locationId": "asia-east1"` to keep it in Asia. Optional privacy step: `FACE_DETECTION` gives face boxes you can blur in the perception job before frames are stored long term.

## 10. Speech-to-Text, Text-to-Speech and Translation

**What:** the Voice Agent's ears, voice and language support, in Thai, Japanese and English. **Deployed by:** a gcloud command for the recognizers; the other two only need their APIs enabled.

```bash
# Speech-to-Text v2: one recognizer per language, in a location that offers Chirp 3
export SPEECH_LOCATION=us          # check where chirp_3 is offered; asia-southeast1 may be available
for pair in th-TH:valz-th ja-JP:valz-ja en-US:valz-en; do
  gcloud ml speech recognizers create ${pair#*:} --location=$SPEECH_LOCATION \
    --model=chirp_3 --language-codes=${pair%%:*}
done

# Text-to-Speech: list the voices, then pick one per language
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://texttospeech.googleapis.com/v1/voices?languageCode=th-TH" | head -40
curl -s -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" \
  https://texttospeech.googleapis.com/v1/text:synthesize -d '{
    "input": {"text": "สวัสดีครับ"},
    "voice": {"languageCode": "th-TH", "name": "th-TH-Chirp3-HD-Aoede"},
    "audioConfig": {"audioEncoding": "MP3"}}' | python3 -c "import sys,json,base64; open('hello.mp3','wb').write(base64.b64decode(json.load(sys.stdin)['audioContent']))"

# Translation: fixed labels in the report languages
curl -s -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" \
  "https://translation.googleapis.com/v3/projects/$PROJECT_ID/locations/global:translateText" \
  -d '{"contents":["Did a part jam?"],"targetLanguageCode":"th","mimeType":"text/plain"}'
```

**Check:** `hello.mp3` plays; the translation returns Thai text; `gcloud ml speech recognizers list --location=$SPEECH_LOCATION` shows three recognizers.
**Gotchas:** the voice name above is an example; use one from the list call. The browser streams the microphone to `valz-api` over a WebSocket (Cloud Run supports WebSockets; keep the request timeout at 3600 s), and `valz-api` streams it to Speech-to-Text. The Gemini Live API is an alternative that does listening, reasoning and speaking in one connection if you want lower latency.

## 11. Cloud Run: valz-api

**What:** the FastAPI service: Gemba Kaizen Engine, Safety, Gemba Kaizen and Voice agents, the signed-URL endpoint and the SSE stream. **Deployed by:** Cloud Build (§18) in steady state; the commands below are the manual first deploy.

```bash
TAG=$(git rev-parse --short HEAD)
gcloud builds submit ai_backend --tag $AR/valz-api:$TAG

gcloud run deploy valz-api \
  --image=$AR/valz-api:$TAG --region=$REGION --service-account=$(sa api) \
  --port=8000 --cpu=2 --memory=4Gi --concurrency=4 --timeout=3600 \
  --min-instances=1 --max-instances=10 --no-cpu-throttling \
  --no-allow-unauthenticated \
  --set-env-vars=GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$VERTEX_LOCATION \
  --set-env-vars=VLM_MODEL=<gemini-vision-model>,LSS_LLM_MODEL=<gemini-text-model>,VOICE_LLM_MODEL=<gemini-text-model> \
  --set-env-vars=RAW_BUCKET=$RAW,PROCESSED_BUCKET=$PROCESSED,RAG_CORPUS=<projects/.../ragCorpora/...>,SPEECH_LOCATION=$SPEECH_LOCATION \
  --set-secrets=ALERT_WEBHOOK=valz-alert-webhook:latest

export API_URL=$(gcloud run services describe valz-api --region=$REGION --format='value(status.url)')

# Callers: the frontend proxy, Cloud Scheduler, Pub/Sub push, the workflow
for s in frontend scheduler pubsub pipeline; do
  gcloud run services add-iam-policy-binding valz-api --region=$REGION \
    --member="serviceAccount:$(sa $s)" --role=roles/run.invoker
done

# Push subscriptions (OIDC) to the internal endpoints
gcloud pubsub subscriptions create segment-uncertain-push --topic=segment.uncertain \
  --push-endpoint=$API_URL/internal/pubsub/uncertain \
  --push-auth-service-account=$(sa pubsub) --push-auth-token-audience=$API_URL \
  --ack-deadline=60 --dead-letter-topic=segment.uncertain.dlq --max-delivery-attempts=5
```

`RAW_BUCKET`, `PROCESSED_BUCKET`, `RAG_CORPUS` and `SPEECH_LOCATION` are read by the migrated code, not by today's image.

**Interim path: today's image, unchanged.** To put the existing backend on Cloud Run before the migration, store the old keys as secrets and pass them through:

```bash
printf '%s' '<key>' | gcloud secrets create openrouter-api-key --data-file=-
printf '%s' '<key>' | gcloud secrets create elevenlabs-api-key --data-file=-
for s in openrouter-api-key elevenlabs-api-key; do
  gcloud secrets add-iam-policy-binding $s --member="serviceAccount:$(sa api)" --role=roles/secretmanager.secretAccessor
done
# add to the deploy command in place of the Vertex variables:
#   --set-secrets=OPENROUTER_API_KEY=openrouter-api-key:latest,ELEVENLABS_API_KEY=elevenlabs-api-key:latest
```

Uploads over 32 MiB will fail until the signed-URL endpoint exists; in the interim use clips under 30 MB or the cached demo clips. Delete both secrets when the migration is done.
**Check:** `curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" $API_URL/health` returns `"status":"healthy"` (`degraded` until a vision model is reachable).
**Gotchas:** `--port=8000` matches the existing Dockerfile (Cloud Run would otherwise expect 8080). `--no-cpu-throttling` keeps CPU on between requests so the SSE stream and the WebSocket work. `/app/data` is ephemeral on Cloud Run: nothing the app needs may live there. Roll back with `gcloud run services update-traffic valz-api --region=$REGION --to-revisions=<previous>=100`.

## 12. Cloud Run job: valz-perception

**What:** samples keyframes with motion energy for one clip and calls Video Intelligence for people counts. A job, not a service, because it runs to completion for each clip. **Deployed by:** Cloud Build (§18); manual first deploy below.

```bash
gcloud builds submit ai_backend --tag $AR/valz-perception:$TAG   # see the note: needs its own entrypoint

gcloud run jobs deploy valz-perception \
  --image=$AR/valz-perception:$TAG --region=$REGION --service-account=$(sa perception) \
  --cpu=2 --memory=4Gi --task-timeout=1800 --max-retries=1 \
  --set-env-vars=PROCESSED_BUCKET=$PROCESSED

# Try it on a clip already in the raw bucket
gcloud run jobs execute valz-perception --region=$REGION --wait \
  --update-env-vars=RUN_ID=run_test,GCS_URI=gs://$RAW/run_test/clip.mp4
```

The job's entrypoint (a short `perception_job.py` that reads `RUN_ID` and `GCS_URI`, writes keyframes to `gs://$PROCESSED/$RUN_ID/frames/` and the people count to `.../people.json`) is part of the code migration; it can reuse `video_utils.py` and the frame-sampling code in `ai_backend`. Give it its own small Dockerfile so it does not carry the API's dependencies.
**Check:** `gcloud run jobs executions list --job=valz-perception --region=$REGION` shows `Succeeded`, and `gs://$PROCESSED/run_test/frames/` has JPEGs.

## 13. Workflows and Eventarc

**What:** Workflows is the pipeline orchestrator (node 05): Transcoder, then the perception job, then the agents. Eventarc starts it when a clip lands in `raw-clips`. **Deployed by:** gcloud.

Save as `deploy/valz-pipeline.yaml`:

```yaml
main:
  params: [event]
  steps:
    - init:
        assign:
          - project: ${sys.get_env("GOOGLE_CLOUD_PROJECT_ID")}
          - region: "asia-southeast1"
          - processed: "<PROJECT_ID>-valz-processed"
          - api: "<API_URL>"
          - object: ${event.data.name}
          - run_id: ${text.split(object, "/")[0]}
          - gcs_uri: ${"gs://" + event.data.bucket + "/" + object}
    - transcode:
        call: http.post
        args:
          url: ${"https://transcoder.googleapis.com/v1/projects/" + project + "/locations/" + region + "/jobs"}
          auth: {type: OAuth2}
          body:
            inputUri: ${gcs_uri}
            outputUri: ${"gs://" + processed + "/" + run_id + "/transcoded/"}
            templateId: preset/web-hd
        result: job
    - wait_for_transcode:
        call: http.get
        args:
          url: ${"https://transcoder.googleapis.com/v1/" + job.body.name}
          auth: {type: OAuth2}
        result: status
    - check_transcode:
        switch:
          - condition: ${status.body.state == "SUCCEEDED"}
            next: perceive
          - condition: ${status.body.state == "FAILED"}
            raise: ${"transcode failed for " + run_id}
        next: pause
    - pause:
        call: sys.sleep
        args: {seconds: 5}
        next: wait_for_transcode
    - perceive:
        call: googleapis.run.v2.projects.locations.jobs.run
        args:
          name: ${"projects/" + project + "/locations/" + region + "/jobs/valz-perception"}
          body:
            overrides:
              containerOverrides:
                - env:
                    - {name: RUN_ID, value: "${run_id}"}
                    - {name: GCS_URI, value: "${gcs_uri}"}
    - reason:
        call: http.post
        args:
          url: ${api + "/internal/pipeline/reason"}
          auth: {type: OIDC, audience: "${api}"}
          body: {run_id: "${run_id}", gcs_uri: "${gcs_uri}"}
          timeout: 900
        result: reasoned
    - done:
        return: ${reasoned.body}
```

Replace the three `<…>` placeholders, then:

```bash
gcloud workflows deploy valz-pipeline --location=$REGION --source=deploy/valz-pipeline.yaml \
  --service-account=$(sa pipeline)

gcloud eventarc triggers create valz-clip-uploaded --location=$REGION \
  --destination-workflow=valz-pipeline --destination-workflow-location=$REGION \
  --event-filters="type=google.cloud.storage.object.v1.finalized" \
  --event-filters="bucket=$RAW" \
  --service-account=$(sa pipeline)
```

**Check:** `gcloud storage cp clip.mp4 gs://$RAW/run_test2/clip.mp4`, then `gcloud workflows executions list valz-pipeline --location=$REGION` shows a run that reaches `SUCCEEDED`; `gcloud workflows executions describe-last valz-pipeline --location=$REGION` shows the error if not.
**Gotchas:** the Eventarc trigger and the bucket must be in the same location. Transcoder and the Cloud Run job both write to `processed`, so `valz-pipeline` needs `storage.objectUser` (granted in §1). Because the first path segment is the `run_id`, `valz-api` must put the upload at `gs://$RAW/<run_id>/<file>`, as in the upload contract.

## 14. Cloud Run: valz-frontend

**What:** the SvelteKit dashboard and its `/api/*` proxy to `valz-api`. **Deployed by:** Cloud Build (§18); manual first deploy below.

```bash
gcloud builds submit frontend --tag $AR/valz-frontend:$TAG

gcloud run deploy valz-frontend \
  --image=$AR/valz-frontend:$TAG --region=$REGION --service-account=$(sa frontend) \
  --port=3000 --cpu=1 --memory=512Mi --concurrency=80 --timeout=900 \
  --min-instances=1 --max-instances=10 \
  --ingress=internal-and-cloud-load-balancing --allow-unauthenticated \
  --set-env-vars=AI_BACKEND_URL=$API_URL,ALLOW_BACKEND_OVERRIDE=false,ORIGIN=https://$DOMAIN
```

Only the load balancer can reach this service (`--ingress`), so `--allow-unauthenticated` means "no Cloud Run IAM check"; the sign-in is IAP at the load balancer (§15).
**Check:** the service URL itself returns an error (blocked ingress); the same page works through the domain after §15.
**Gotchas:** `ORIGIN` must be the public `https://` address or SvelteKit rejects form posts. `ALLOW_BACKEND_OVERRIDE=false` stops the UI from pointing the proxy at an address a visitor types. The proxy must attach a Google ID token for the `valz-api` audience (the code change in the architecture page).

## 15. Load balancer, Cloud CDN, Cloud Armor, IAP and DNS

**What:** one public HTTPS address in front of everything. **Deployed by:** gcloud, plus a one-time OAuth consent screen in the console.

```bash
# Address and DNS
gcloud compute addresses create valz-ip --global --ip-version=IPV4
export IP=$(gcloud compute addresses describe valz-ip --global --format='value(address)')
gcloud dns managed-zones create valz-zone --dns-name="<your-domain>." --description="VALZ"   # skip if the zone exists
gcloud dns record-sets create $DOMAIN. --zone=valz-zone --type=A --ttl=300 --rrdatas=$IP

# Backends: Cloud Run through a serverless NEG, and the static bucket
gcloud compute network-endpoint-groups create valz-fe-neg --region=$REGION \
  --network-endpoint-type=serverless --cloud-run-service=valz-frontend
gcloud compute backend-services create valz-fe-bes --global --load-balancing-scheme=EXTERNAL_MANAGED
gcloud compute backend-services add-backend valz-fe-bes --global \
  --network-endpoint-group=valz-fe-neg --network-endpoint-group-region=$REGION
gcloud compute backend-services update valz-fe-bes --global --enable-cdn --cache-mode=USE_ORIGIN_HEADERS
gcloud compute backend-buckets create valz-static-bb --gcs-bucket-name=$STATIC \
  --enable-cdn --cache-mode=CACHE_ALL_STATIC

# Routing: demo clips from the bucket, everything else to the frontend
gcloud compute url-maps create valz-map --default-service=valz-fe-bes
gcloud compute url-maps add-path-matcher valz-map --path-matcher-name=static \
  --default-service=valz-fe-bes --backend-bucket-path-rules="/demo/*=valz-static-bb" \
  --new-hosts=$DOMAIN

# TLS and the front door
gcloud compute ssl-certificates create valz-cert --domains=$DOMAIN --global
gcloud compute target-https-proxies create valz-https-proxy --url-map=valz-map --ssl-certificates=valz-cert
gcloud compute forwarding-rules create valz-fr --global --load-balancing-scheme=EXTERNAL_MANAGED \
  --network-tier=PREMIUM --address=valz-ip --target-https-proxy=valz-https-proxy --ports=443

# Cloud Armor: WAF rule and a per-IP rate limit
gcloud compute security-policies create valz-armor --description="VALZ edge"
gcloud compute security-policies rules create 1000 --security-policy=valz-armor \
  --expression="evaluatePreconfiguredWaf('xss-v33-stable')" --action=deny-403
gcloud compute security-policies rules create 2000 --security-policy=valz-armor \
  --src-ip-ranges="*" --action=throttle --rate-limit-threshold-count=300 \
  --rate-limit-threshold-interval-sec=60 --conform-action=allow --exceed-action=deny-429 --enforce-on-key=IP
gcloud compute backend-services update valz-fe-bes --global --security-policy=valz-armor
```

**IAP.** In the console go to APIs & Services → OAuth consent screen (set it to Internal for a Google Workspace org, otherwise External with test users) and create an OAuth client of type Web application. Store its secret in Secret Manager, then:

```bash
gcloud compute backend-services update valz-fe-bes --global \
  --iap=enabled,oauth2-client-id=<CLIENT_ID>,oauth2-client-secret=<CLIENT_SECRET>
gcloud iap web add-iam-policy-binding --resource-type=backend-services --service=valz-fe-bes \
  --member="group:valz-managers@<your-domain>" --role=roles/iap.httpsResourceAccessor
```

**Check:** `gcloud compute ssl-certificates describe valz-cert --global --format="value(managed.status)"` becomes `ACTIVE` (up to an hour after the DNS record resolves); then `https://$DOMAIN` asks for a Google sign-in and shows the dashboard.
**Gotchas:** the `/demo/*` path goes to the bucket without IAP, so it must hold demo material only. Dynamic responses are not cached because the frontend backend uses `USE_ORIGIN_HEADERS`; have the API send `Cache-Control: no-store`. Add an HTTP-to-HTTPS redirect with a second forwarding rule if you need port 80.

## 16. BigQuery and Looker Studio

**What:** cross-shift analytics for the plant manager: waste, ROI, which actions were approved. **Deployed by:** `bq` for the dataset; the report is built in the Looker Studio UI (it has no deploy command).

```bash
bq --location=$REGION mk --dataset $PROJECT_ID:valz_analytics
bq mk --table valz_analytics.cards \
  run_id:STRING,card_id:STRING,category:STRING,priority:STRING,decision:STRING,hours_saved_per_shift:FLOAT,decided_at:TIMESTAMP
bq mk --table valz_analytics.runs \
  run_id:STRING,station_name:STRING,va_percent:FLOAT,nva_hours_per_shift:FLOAT,incidents:INTEGER,created_at:TIMESTAMP
```

In Looker Studio: Create → Data source → BigQuery → `valz_analytics.cards`, then build the report and share it with the managers group.
**Check:** after §17's sync runs, `bq query 'SELECT COUNT(*) FROM valz_analytics.cards'` returns rows.

## 17. Cloud Tasks and Cloud Scheduler

**What:** Cloud Tasks re-asks operator questions nobody answered; Cloud Scheduler runs the nightly BigQuery sync. **Deployed by:** gcloud.

```bash
gcloud tasks queues create valz-question-retry --location=$REGION \
  --max-attempts=3 --min-backoff=60s --max-backoff=300s

gcloud scheduler jobs create http valz-bq-sync --location=$REGION \
  --schedule="0 2 * * *" --time-zone="Asia/Bangkok" \
  --uri="$API_URL/internal/sync/bigquery" --http-method=POST \
  --oidc-service-account-email=$(sa scheduler) --oidc-token-audience=$API_URL
```

**Check:** `gcloud scheduler jobs run valz-bq-sync --location=$REGION`, then look at the `valz-api` logs for the sync request.

## 18. Cloud Build and Cloud Deploy

**What:** Cloud Build turns every push to `main` into new images and a new Cloud Run revision. Cloud Deploy, if you want it, adds a staging → production promotion. **Deployed by:** a one-time trigger; then every push.

Save as `cloudbuild.yaml` at the repository root:

```yaml
substitutions:
  _REGION: asia-southeast1
  _AR: asia-southeast1-docker.pkg.dev/${PROJECT_ID}/valz
serviceAccount: projects/${PROJECT_ID}/serviceAccounts/valz-build@${PROJECT_ID}.iam.gserviceaccount.com
options:
  logging: CLOUD_LOGGING_ONLY
steps:
  - {name: gcr.io/cloud-builders/docker, args: [build, -t, '${_AR}/valz-api:${SHORT_SHA}', ai_backend]}
  - {name: gcr.io/cloud-builders/docker, args: [build, -t, '${_AR}/valz-frontend:${SHORT_SHA}', frontend]}
  - {name: gcr.io/cloud-builders/docker, args: [push, '${_AR}/valz-api:${SHORT_SHA}']}
  - {name: gcr.io/cloud-builders/docker, args: [push, '${_AR}/valz-frontend:${SHORT_SHA}']}
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args: [run, deploy, valz-api, '--image=${_AR}/valz-api:${SHORT_SHA}', '--region=${_REGION}']
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args: [run, deploy, valz-frontend, '--image=${_AR}/valz-frontend:${SHORT_SHA}', '--region=${_REGION}']
```

`gcloud run deploy` with only `--image` keeps the settings from §11 and §14. Add a step for `valz-perception` the same way with `gcloud run jobs deploy`.

```bash
# One-time: connect the GitHub repository in the console (Cloud Build → Triggers → Connect repository), then:
gcloud builds triggers create github --name=valz-main \
  --repo-owner=<github-owner> --repo-name=<repo> --branch-pattern='^main$' \
  --build-config=cloudbuild.yaml \
  --service-account=projects/$PROJECT_ID/serviceAccounts/valz-build@$PROJECT_ID.iam.gserviceaccount.com
```

**Cloud Deploy (optional).** One pipeline per service, shown for `valz-api`; repeat for `valz-frontend`.

```yaml
# clouddeploy.yaml
apiVersion: deploy.cloud.google.com/v1
kind: DeliveryPipeline
metadata: {name: valz-api}
serialPipeline:
  stages: [{targetId: staging}, {targetId: prod}]
---
apiVersion: deploy.cloud.google.com/v1
kind: Target
metadata: {name: staging}
run: {location: projects/<PROJECT_ID>/locations/asia-southeast1}
---
apiVersion: deploy.cloud.google.com/v1
kind: Target
metadata: {name: prod}
requireApproval: true
run: {location: projects/<PROJECT_ID>/locations/asia-southeast1}
```

```bash
gcloud deploy apply --file=clouddeploy.yaml --region=$REGION
gcloud deploy releases create rel-$TAG --delivery-pipeline=valz-api --region=$REGION \
  --images=valz-api=$AR/valz-api:$TAG
gcloud deploy releases promote --release=rel-$TAG --delivery-pipeline=valz-api --region=$REGION
```

The release needs a `skaffold.yaml` and a Cloud Run `service.yaml` beside it (`deploy.cloudrun` with the service manifest as `manifests.rawYaml`); the Cloud Deploy quickstart for Cloud Run has the exact files. For a 24-hour hackathon, Cloud Build alone is enough.
**Check:** push a trivial change to `main`; `gcloud builds list --limit=1` shows `SUCCESS` and `gcloud run revisions list --service=valz-api --region=$REGION` shows a new revision.

## 19. Logging, Monitoring, Trace, Error Reporting and budgets

**What:** you see what the system is doing and are warned before it costs too much. **Deployed by:** automatic for Cloud Run; a few gcloud commands for alerts and the budget.

- **Cloud Logging:** everything written to stdout and stderr is collected. Write one JSON object per line (`severity`, `message`, `run_id`) and the fields become searchable: `resource.type="cloud_run_revision" jsonPayload.run_id="run_20261017_0412"`.
- **Error Reporting:** groups unhandled exceptions from the same logs; no setup beyond logging stack traces.
- **Cloud Trace:** Cloud Run forwards trace headers; add `opentelemetry-exporter-gcp-trace` to `valz-api` to see how long Gemini, Firestore and Speech take inside one request.
- **Cloud Monitoring:** in the console, Monitoring → Uptime checks → create an HTTPS check on `https://$DOMAIN/api/health` (it needs the IAP-exempt health path or an IAP-authenticated check), and an alert policy to your email or the alert webhook.

```bash
gcloud logging metrics create valz_question_unanswered \
  --description="Operator questions that expired unanswered" \
  --log-filter='resource.type="cloud_run_revision" jsonPayload.event="question_unanswered"'

gcloud billing budgets create --billing-account=$BILLING_ACCOUNT --display-name="VALZ" \
  --budget-amount=100USD \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 --threshold-rule=percent=1.0
```

**Check:** the budget appears under Billing → Budgets & alerts; the metric under Logging → Log-based metrics.
**Cost levers:** `--min-instances` on Cloud Run is the main fixed cost (set to 1 for the demo, 0 otherwise); Gemini and Video Intelligence are per use, so cache results for the demo clips; the bucket lifecycle rules keep storage flat.

## 20. Verify end to end

1. `https://$DOMAIN` asks for Google sign-in and loads the dashboard; the cached demo clip plays and its cards show (this works with no backend).
2. Upload a clip in the Video page. In the Network tab the `PUT` goes to `storage.googleapis.com`, not to your domain.
3. `gcloud workflows executions list valz-pipeline --location=$REGION` shows a new run that ends `SUCCEEDED`.
4. In the Firestore console, `runs/<run_id>` has `status: ready`, with segments and cards beneath it.
5. A grey (`UNCERTAIN`) segment appears; the Voice page asks the question in Thai and plays it; answering marks it `verified` and the ROI changes.
6. `bq query 'SELECT COUNT(*) FROM valz_analytics.cards'` grows after the nightly sync (or run the Scheduler job by hand).

## 21. Tear down

```bash
gcloud projects delete $PROJECT_ID      # removes everything, billing stops; recoverable for 30 days
```

To remove only the paid always-on parts, set both Cloud Run services to `--min-instances=0`, delete the forwarding rule `valz-fr` and the reserved address `valz-ip`. Cloud KMS key versions are scheduled for destruction, not deleted at once, and a deleted project name cannot be reused.
