# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please do NOT open a public issue.

Instead, send a description of the issue to the project maintainers via GitHub Security Advisory or contact the repository owner directly.

Please include:
- Type of vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

You should receive a response within 48 hours. If the issue is confirmed, a fix will be coordinated and released as soon as possible.

## Security Best Practices

### For Production Deployments

1. **JWT Secrets**: Always set `JWT_SECRET` and `JWT_REFRESH_SECRET` to strong random values. Generate with:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

2. **Database**: Use strong passwords for PostgreSQL. Never use the default `finn:finn` credentials in production.

3. **HTTPS**: Configure SSL/TLS termination at the reverse proxy level. The built-in nginx config listens on port 80 only — use a TLS-terminating proxy (Cloudflare, another nginx with certbot, etc.) in front.

4. **Redis**: Set `REDIS_PASSWORD` and ensure Redis is not exposed to public networks.

5. **API Rate Limiting**: The API has built-in rate limiting via slowapi. Configure appropriate limits for your use case.

6. **Metrics Endpoint**: The `/metrics` endpoint exposes Prometheus metrics. Set `METRICS_TOKEN` or restrict access to localhost only.

7. **Broker Tokens**: Store broker API tokens in environment variables or a secure vault. Never commit them to the repository.

### Development

- Never commit `.env` files containing real secrets
- Use sandbox/test modes for broker APIs during development
- Enable `TINKOFF_SANDBOX=true` when testing with T-Bank API
