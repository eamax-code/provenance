# 06: Configure an email provider

**What to build:** SMTP (or a transactional provider) so approved key requests can be emailed and email watches work; the path is implemented but untested against a real server.

**Blocked by:** 02

**Status:** ready-for-human (provider account, sender domain), then ready-for-agent (end-to-end test)

- [ ] Sender domain with SPF/DKIM; `EMAIL_PROVIDER=smtp` settings in the platform secrets
- [ ] One approved key request delivered by email; one email watch delivery observed
