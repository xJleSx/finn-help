FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM node:22-alpine AS runner

RUN addgroup -S finn && adduser -S finn -G finn
WORKDIR /app

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/next.config.ts ./next.config.ts

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

USER finn
EXPOSE 3000

CMD ["npm", "start"]