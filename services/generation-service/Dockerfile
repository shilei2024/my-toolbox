ARG NPM_REGISTRY=https://registry.npmjs.org
FROM node:24-bookworm-slim

ARG NPM_REGISTRY

ENV NODE_ENV=production
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --registry=$NPM_REGISTRY && npm cache clean --force

COPY src ./src
COPY workflows ./workflows

RUN mkdir -p /tmp/generation && chown -R node:node /app /tmp/generation
USER node

CMD ["npm", "run", "gallery:start"]

