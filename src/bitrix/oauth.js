import axios from "axios";

const AUTH_BASE_URL = "https://oauth.bitrix.info/oauth";

export class BitrixOAuthClient {
  constructor({ clientId, clientSecret, redirectUri, scopes }) {
    this.clientId = clientId;
    this.clientSecret = clientSecret;
    this.redirectUri = redirectUri;
    this.scopes = scopes;
  }

  canAuthorize() {
    return Boolean(this.clientId && this.clientSecret && this.redirectUri);
  }

  getAuthorizationUrl(state = "") {
    if (!this.canAuthorize()) {
      throw new Error("BITRIX_CLIENT_ID / BITRIX_CLIENT_SECRET / BITRIX_REDIRECT_URI are not configured.");
    }

    const params = new URLSearchParams({
      client_id: this.clientId,
      response_type: "code",
      redirect_uri: this.redirectUri,
      scope: this.scopes,
    });

    if (state) params.set("state", state);
    return `${AUTH_BASE_URL}/authorize/?${params.toString()}`;
  }

  async exchangeCode(code) {
    if (!code) throw new Error("OAuth code is required.");

    const params = new URLSearchParams({
      grant_type: "authorization_code",
      client_id: this.clientId,
      client_secret: this.clientSecret,
      code,
      redirect_uri: this.redirectUri,
    });

    const { data } = await axios.get(`${AUTH_BASE_URL}/token/?${params.toString()}`, {
      timeout: 15_000,
    });

    return data;
  }

  async refreshToken(refreshToken) {
    const params = new URLSearchParams({
      grant_type: "refresh_token",
      client_id: this.clientId,
      client_secret: this.clientSecret,
      refresh_token: refreshToken,
    });

    const { data } = await axios.get(`${AUTH_BASE_URL}/token/?${params.toString()}`, {
      timeout: 15_000,
    });

    return data;
  }
}
