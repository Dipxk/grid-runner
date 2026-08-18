# Optional AWS telemetry architecture

Grid Runner keeps **planning and collision avoidance local**. AWS is only for
observability when you choose to wire it in.

```
Grid Runner (FastAPI)
        │
        ▼
  TelemetrySink  ──►  MQTT (AWS IoT Core)
        │                    │
        │                    ▼
        │                 Lambda
        │                ╱      ╲
        │          DynamoDB    S3
        ▼
   local JSON / console
```

Topics (planned):

- `gridrunner/fleet/metrics`
- `gridrunner/robots/{id}/state`
- `gridrunner/events/fault`
- `gridrunner/events/recovery`

Implement `AwsIotTelemetrySink` when credentials and `awsiotsdk` are available.
The core simulator runs without AWS installed.
