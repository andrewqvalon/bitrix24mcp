import fs from "node:fs/promises";
import path from "node:path";

export class TokenStore {
  constructor(filePath) {
    this.filePath = filePath;
  }

  async ensureDir() {
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });
  }

  async read() {
    try {
      const raw = await fs.readFile(this.filePath, "utf8");
      return JSON.parse(raw);
    } catch (error) {
      if (error && error.code === "ENOENT") return null;
      throw error;
    }
  }

  async write(tokens) {
    await this.ensureDir();
    await fs.writeFile(this.filePath, JSON.stringify(tokens, null, 2), "utf8");
  }
}

export class TokenManager {
  constructor({ store, oauthClient }) {
    this.store = store;
    this.oauthClient = oauthClient;
    this.refreshPromise = null;
  }

  async saveFromOAuthResponse(payload) {
    const now = Date.now();
    const expiresInSec = Number(payload.expires_in ?? 3600);
    const record = {
      access_token: payload.access_token,
      refresh_token: payload.refresh_token,
      expires_at: now + expiresInSec * 1000,
      domain: payload.domain ?? null,
      client_endpoint: payload.client_endpoint ?? null,
      server_endpoint: payload.server_endpoint ?? null,
      member_id: payload.member_id ?? null,
      scope: payload.scope ?? null,
      updated_at: new Date(now).toISOString(),
    };

    await this.store.write(record);
    return record;
  }

  async getTokens() {
    return this.store.read();
  }

  async requireTokens() {
    const tokens = await this.getTokens();
    if (!tokens?.access_token) {
      throw new Error("Bitrix24 is not authorized. Open /auth/bitrix/start first.");
    }
    return tokens;
  }

  isExpired(tokens) {
    const expiresAt = Number(tokens?.expires_at ?? 0);
    if (!expiresAt) return true;
    return Date.now() >= expiresAt - 60_000;
  }

  async getValidTokens() {
    const current = await this.requireTokens();
    if (!this.isExpired(current)) return current;
    return this.refresh();
  }

  async refresh() {
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    this.refreshPromise = (async () => {
      const current = await this.requireTokens();
      if (!current.refresh_token) {
        throw new Error("Refresh token is missing. Re-authorize in Bitrix24.");
      }

      const payload = await this.oauthClient.refreshToken(current.refresh_token);
      return this.saveFromOAuthResponse(payload);
    })();

    try {
      return await this.refreshPromise;
    } finally {
      this.refreshPromise = null;
    }
  }
}
