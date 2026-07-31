# OpenAI-CPA email bridge on public Server 1

## Paths
- CF Worker webhook: `POST /api/webhook/email` + header `X-Webhook-Secret`
- Local opaiRe client: `GET/WS /api/email-bridge/check|ws/{email}` + `Authorization: Bearer ...`
- Health: `GET /api/email-bridge/health` or `/health`

## CF Worker
- Repo: wenfxl/openai-cpa-email
- `EMAIL_WEBHOOK_URL=https://tupai.cyou`  (empty path auto-appends `/api/webhook/email`)
- `EMAIL_WEBHOOK_SECRET=<same as server webhook token>`

## Local opaiRe config.yaml
```yaml
email_api_mode: openai_cpa
openai_cpa:
  webhook_secret: <same>
  bridge_enabled: true
  bridge_base_url: https://tupai.cyou
  bridge_token: <same or dedicated>
```

## Server notes
- Runs on 127.0.0.1:8820
- Nginx must expose webhook/bridge paths WITHOUT cliproxy auth_request
- Do not put secrets in docs commits
