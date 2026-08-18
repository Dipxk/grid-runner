# Optional AWS telemetry architecture

RoboFleet keeps **planning and collision avoidance local**. AWS is only for
observability when you choose to wire it in.

```
RoboFleet (FastAPI on Render/local)
        │
        ▼
  TelemetryBridge  ──►  TelemetrySink
        │                    │
        │                    ├── Console / JSON (local, works today)
        │                    │
        │                    └── MQTT (AWS IoT Core)
        │                              │
        │                              ▼
        │                           Lambda
        │                          ╱      ╲
        │                    DynamoDB      S3
        ▼
   benchmarks/telemetry.jsonl
```

## What gets published

| Topic | Payload |
| --- | --- |
| `gridrunner/fleet/metrics` | Rolling throughput, tick compute, collisions, fault counts (every 30 ticks) |
| `gridrunner/events/fault` | `fault_detected`, `robot_offline`, `planner_failure`, `task_reassigned` |
| `gridrunner/events/recovery` | `recovery_started`, `recovery_completed`, `robot_recovered` |
| `gridrunner/events/scenario-start` | Scenario begin |
| `gridrunner/events/scenario-over` | Scenario grade/score |

Planning, reservations, and the execution guard **never** run in AWS.

---

## Local telemetry (no AWS)

Works out of the box. By default the server writes to `benchmarks/telemetry.jsonl`.

```bash
# console only
GRIDRUNNER_TELEMETRY=console make run

# explicit JSON path
GRIDRUNNER_TELEMETRY=json GRIDRUNNER_TELEMETRY_PATH=/tmp/grid.jsonl make run

# disable
GRIDRUNNER_TELEMETRY=null make run
```

Check `/api/health` — it reports which sink is active:

```json
{"status":"ok","telemetry":["json"],"path":".../benchmarks/telemetry.jsonl"}
```

---

## AWS IoT setup (optional)

### 1. Install the SDK (only on hosts that publish to AWS)

```bash
pip install -r backend/requirements-aws.txt
```

### 2. Create IoT resources (AWS Console or CLI)

1. **IoT Core → Things → Create** — name it `grid-runner`
2. **Certificates** — create + activate, download:
   - `device.pem.crt`
   - `private.pem.key`
   - `AmazonRootCA1.pem` (optional if using system CA)
3. **Policy** — allow connect + publish:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["iot:Connect"],
      "Resource": "arn:aws:iot:REGION:ACCOUNT:client/grid-runner"
    },
    {
      "Effect": "Allow",
      "Action": ["iot:Publish"],
      "Resource": "arn:aws:iot:REGION:ACCOUNT:topic/gridrunner/*"
    }
  ]
}
```

4. Attach policy to the certificate.

### 3. Configure RoboFleet

```bash
export GRIDRUNNER_TELEMETRY=aws   # or "all" for JSON + AWS

export AWS_IOT_ENDPOINT=xxxxxxxxxx-ats.iot.us-east-1.amazonaws.com
export AWS_IOT_CERT_PATH=/path/to/device.pem.crt
export AWS_IOT_KEY_PATH=/path/to/private.pem.key
export AWS_IOT_CA_PATH=/path/to/AmazonRootCA1.pem   # optional
export AWS_IOT_CLIENT_ID=grid-runner
export AWS_IOT_TOPIC_PREFIX=gridrunner

make run
```

If credentials are missing or `awsiotsdk` is not installed, the sim **still runs**;
AWS publish is skipped with a log warning.

### 4. Lambda → DynamoDB (example rule)

**IoT Core → Message routing → Rules:**

```sql
SELECT * FROM 'gridrunner/events/#'
```

Action: Lambda `gridrunner-ingest` → writes to DynamoDB table `gridrunner_events`:

| pk | sk | payload |
| --- | --- | --- |
| `FAULT#R07` | `tick#1042` | `{...}` |

S3 archival: second rule on `gridrunner/fleet/metrics` → Kinesis Firehose or Lambda → S3 prefix `runs/`.

---

## Render deployment

Add env vars in the Render dashboard (Settings → Environment). **Do not commit certs.**

For free Render, JSON telemetry to ephemeral disk is enough for demos. AWS IoT is
best when you have persistent certs (Secrets Manager, or mounted files on a VM).

Recommended for portfolio demo:

```text
GRIDRUNNER_TELEMETRY=json
```

Upgrade path when you have AWS:

```text
GRIDRUNNER_TELEMETRY=all
AWS_IOT_ENDPOINT=...
AWS_IOT_CERT_PATH=...   # mount via secret file
AWS_IOT_KEY_PATH=...
```

---

## Honest scope

- **Implemented:** `TelemetrySink`, `AwsIotTelemetrySink`, env-based wiring, health status
- **Not included:** Terraform, Lambda code, DynamoDB tables — you add those in your AWS account
- **Core sim:** runs with zero AWS dependencies
