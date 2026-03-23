import axios from "axios";

function toArrayPayload(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  return [value];
}

export class BitrixClient {
  constructor({ tokenManager }) {
    this.tokenManager = tokenManager;
  }

  async call(method, params = {}) {
    const tokens = await this.tokenManager.getValidTokens();
    if (!tokens.client_endpoint) {
      throw new Error("Bitrix client endpoint is missing in OAuth tokens.");
    }

    const endpoint = `${tokens.client_endpoint}${method}.json`;
    const requestData = {
      auth: tokens.access_token,
      ...params,
    };

    try {
      const { data } = await axios.post(endpoint, requestData, { timeout: 20_000 });
      if (data?.error) {
        throw new Error(`Bitrix API error: ${data.error} ${data.error_description ?? ""}`.trim());
      }
      return data;
    } catch (error) {
      if (error.response?.status === 401) {
        // One retry after refresh on expired/invalid token.
        await this.tokenManager.refresh();
        const retried = await this.tokenManager.getValidTokens();
        const retryEndpoint = `${retried.client_endpoint}${method}.json`;
        const { data } = await axios.post(
          retryEndpoint,
          { auth: retried.access_token, ...params },
          { timeout: 20_000 },
        );
        if (data?.error) {
          throw new Error(`Bitrix API error: ${data.error} ${data.error_description ?? ""}`.trim());
        }
        return data;
      }
      throw error;
    }
  }

  async listDeals({ limit = 20, select = ["ID", "TITLE", "STAGE_ID", "OPPORTUNITY", "CURRENCY_ID"] } = {}) {
    const data = await this.call("crm.deal.list", {
      start: 0,
      select: toArrayPayload(select),
      order: { ID: "DESC" },
    });

    const rows = Array.isArray(data?.result) ? data.result : [];
    return rows.slice(0, limit);
  }

  async getDeal({ id, select = ["*"] }) {
    if (!id) throw new Error("Deal id is required.");
    const data = await this.call("crm.deal.get", { id, select: toArrayPayload(select) });
    return data?.result ?? null;
  }

  async listContacts({ limit = 20, select = ["ID", "NAME", "LAST_NAME", "PHONE", "EMAIL"] } = {}) {
    const data = await this.call("crm.contact.list", {
      start: 0,
      select: toArrayPayload(select),
      order: { ID: "DESC" },
    });
    const rows = Array.isArray(data?.result) ? data.result : [];
    return rows.slice(0, limit);
  }
}
