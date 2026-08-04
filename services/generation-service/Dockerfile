FROM node:24-bookworm-slim

ENV NODE_ENV=production
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force

COPY src ./src
COPY workflows ./workflows

RUN mkdir -p /tmp/generation && chown -R node:node /app /tmp/generation
USER node

CMD ["npm", "run", "gallery:start"]

