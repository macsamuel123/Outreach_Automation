import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: API_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

// Add token to requests if available
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("github_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export const apiClient = {
  // Auth
  getGithubAuthUrl: () => api.get("/auth/github/url"),
  exchangeGithubCode: (code: string) =>
    api.post("/auth/github/callback", { code }),

  // Dashboard
  getStats: () => api.get("/api/stats"),

  // Partners
  listPartners: (status?: string, skip?: number, limit?: number) =>
    api.get("/api/partners", { params: { status, skip, limit } }),
  updatePartner: (id: number, data: any) =>
    api.put(`/api/partners/${id}`, data),

  // Leads
  listLeads: (status?: string, skip?: number, limit?: number) =>
    api.get("/api/leads", { params: { status, skip, limit } }),

  // Audit Log
  searchAuditLog: (stage?: string, decision?: string, skip?: number, limit?: number) =>
    api.get("/api/audit-log", { params: { stage, decision, skip, limit } }),
  exportAuditLog: () => api.get("/api/audit-log/export"),

  // Runs
  listRuns: (limit?: number) => api.get("/api/runs", { params: { limit } }),
  triggerRun: () => api.post("/api/runs/trigger"),
  getRunLogs: (runId: number) => api.get(`/api/runs/${runId}/logs`),

  // Config
  getConfig: () => api.get("/api/config"),
};

export default api;
