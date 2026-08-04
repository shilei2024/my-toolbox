export interface GalleryCache {
  get<T>(key: string): Promise<T | undefined>;
  set<T>(key: string, value: T, ttlSeconds: number): Promise<void>;
  delete(key: string): Promise<void>;
  version(namespace: string): Promise<string>;
  bump(namespace: string): Promise<void>;
}

export class NoopGalleryCache implements GalleryCache {
  async get<T>(_key: string): Promise<T | undefined> { return undefined; }
  async set<T>(_key: string, _value: T, _ttlSeconds: number): Promise<void> {}
  async delete(_key: string): Promise<void> {}
  async version(_namespace: string): Promise<string> { return "0"; }
  async bump(_namespace: string): Promise<void> {}
}
