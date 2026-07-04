# ---- Builder ----
FROM node:22-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- Runner (production) ----
FROM node:22-alpine AS runner

RUN addgroup -S finn && adduser -S finn -G finn

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=builder --chown=finn:finn /app/.next/standalone ./
COPY --from=builder --chown=finn:finn /app/.next/static ./.next/static
COPY --from=builder --chown=finn:finn /app/public ./public

USER finn
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/api/health || exit 1

CMD ["node", "server.js"]
