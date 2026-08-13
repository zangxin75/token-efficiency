# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest `main` | ✅ |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report vulnerabilities privately:

1. Email: **security@tokeneff.com**
2. Include a description of the vulnerability
3. Provide steps to reproduce (if applicable)
4. Suggest a fix (if you have one)

### Response Timeline

- **Acknowledgment**: within 48 hours
- **Initial assessment**: within 1 week
- **Fix or mitigation**: depends on severity, communicated via email

## Security Features

This project includes:
- JWT httpOnly cookie authentication
- CSRF protection
- bcrypt password hashing
- API key encryption (Fernet)
- Token version invalidation
- Per-tenant quota enforcement
- Rate limiting with cooldown

## Self-Hosting Security Checklist

If you're self-hosting, make sure to:
- [ ] Change `POSTGRES_PASSWORD` from default
- [ ] Change `LITELLM_MASTER_KEY` from default
- [ ] Change `JWT_SECRET` from default
- [ ] Set `REDIS_PASSWORD`
- [ ] Bind PostgreSQL/Redis to internal network only (not `0.0.0.0`)
- [ ] Enable HTTPS via reverse proxy
