import type { Redis } from "ioredis";
import type { GalleryCache } from "./cache.ts";

export class RedisGalleryCache implements GalleryCache {
  readonly #redis: Redis;
  readonly #prefix: string;

  constructor(redis: Redis, prefix = "mavis:gallery") {
    this.#redis = redis;
    this.#prefix = prefix.replace(/:+$/, "");
  }

  async get<T>(key: string): Promise<T | undefined> {
    const value = await this.#redis.get(this.key(key));
    if (!value) return undefined;
    try { return JSON.parse(value) as T; } catch { await this.delete(key); return undefined; }
  }

  async set<T>(key: string, value: T, ttlSeconds: number): Promise<void> {
    await this.#redis.set(this.key(key), JSON.stringify(value), "EX", ttlSeconds);
  }

  async delete(key: string): Promise<void> {
    await this.#redis.del(this.key(key));
  }

  async version(namespace: string): Promise<string> {
    const key = this.key(`version:${namespace}`);
    await this.#redis.set(key, "0", "NX");
    return await this.#redis.get(key) ?? "0";
  }

  async bump(namespace: string): Promise<void> {
    await this.#redis.incr(this.key(`version:${namespace}`));
  }

  private key(value: string): string { return `${this.#prefix}:${value}`; }
}
