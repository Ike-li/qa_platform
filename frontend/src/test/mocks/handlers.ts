import { http, HttpResponse } from "msw";
import {
  mockProjects,
  mockPipelines,
  mockEnvironments,
  mockRunDoneSuccess,
  mockRunRunning,
  mockTestResults,
  mockArtifacts,
  mockApiTokens,
  createMockProject,
  createMockRun,
  createMockApiToken,
} from "./fixtures";

const API_BASE = "/api/v1";

export const handlers = [
  // Auth endpoints
  http.post(`${API_BASE}/auth/login`, () => {
    return HttpResponse.json({ message: "Login successful" });
  }),

  http.post(`${API_BASE}/auth/logout`, () => {
    return HttpResponse.json({ message: "Logout successful" });
  }),

  http.post(`${API_BASE}/auth/refresh`, () => {
    return HttpResponse.json({ message: "Token refreshed" });
  }),

  // Projects endpoints
  http.get(`${API_BASE}/projects`, ({ request }) => {
    const url = new URL(request.url);
    const q = url.searchParams.get("q");

    let filtered = mockProjects;
    if (q) {
      filtered = mockProjects.filter((p) =>
        p.name.toLowerCase().includes(q.toLowerCase())
      );
    }

    return HttpResponse.json({
      data: filtered,
      total: filtered.length,
      page: 1,
      per_page: 20,
    });
  }),

  http.get(`${API_BASE}/projects/:id`, ({ params }) => {
    const project = mockProjects.find((p) => p.id === params.id);
    if (!project) {
      return new HttpResponse(null, { status: 404 });
    }
    return HttpResponse.json(project);
  }),

  http.post(`${API_BASE}/projects`, async ({ request }) => {
    const body = await request.json() as any;
    const newProject = createMockProject({
      name: body.name,
      slug: body.slug,
      git_url: body.git_url,
    });
    return HttpResponse.json(newProject, { status: 201 });
  }),

  http.patch(`${API_BASE}/projects/:id`, async ({ params, request }) => {
    const project = mockProjects.find((p) => p.id === params.id);
    if (!project) {
      return new HttpResponse(null, { status: 404 });
    }
    const body = await request.json() as any;
    return HttpResponse.json({ ...project, ...body });
  }),

  http.delete(`${API_BASE}/projects/:id`, ({ params }) => {
    const project = mockProjects.find((p) => p.id === params.id);
    if (!project) {
      return new HttpResponse(null, { status: 404 });
    }
    return new HttpResponse(null, { status: 204 });
  }),

  // Pipelines endpoints
  http.get(`${API_BASE}/projects/:projectId/pipelines`, ({ params }) => {
    const pipelines = mockPipelines.filter((p) => p.project_id === params.projectId);
    return HttpResponse.json({ data: pipelines, total: pipelines.length });
  }),

  // Environments endpoints
  http.get(`${API_BASE}/projects/:projectId/environments`, ({ params }) => {
    const environments = mockEnvironments.filter((e) => e.project_id === params.projectId);
    return HttpResponse.json({ data: environments, total: environments.length });
  }),

  // Runs endpoints
  http.get(`${API_BASE}/runs`, () => {
    return HttpResponse.json({
      data: [mockRunDoneSuccess, mockRunRunning],
      total: 2,
      page: 1,
      per_page: 20,
    });
  }),

  http.get(`${API_BASE}/runs/:id`, ({ params }) => {
    if (params.id === "run-success") {
      return HttpResponse.json(mockRunDoneSuccess);
    }
    if (params.id === "run-running") {
      return HttpResponse.json(mockRunRunning);
    }
    return new HttpResponse(null, { status: 404 });
  }),

  http.post(`${API_BASE}/runs`, async ({ request }) => {
    const body = await request.json() as any;
    const newRun = createMockRun({
      pipeline_id: body.pipeline_id,
      environment_id: body.environment_id,
      git_ref: body.branch || "main",
      priority: body.priority || 1,
    });
    return HttpResponse.json(newRun, { status: 201 });
  }),

  http.post(`${API_BASE}/runs/:id/cancel`, ({ params }) => {
    return HttpResponse.json({ message: "Run cancelled" });
  }),

  // Test results endpoints
  http.get(`${API_BASE}/runs/:runId/results`, ({ params }) => {
    return HttpResponse.json({
      data: mockTestResults,
      total: mockTestResults.length,
    });
  }),

  // Artifacts endpoints
  http.get(`${API_BASE}/runs/:runId/artifacts`, ({ params }) => {
    return HttpResponse.json({
      data: mockArtifacts,
      total: mockArtifacts.length,
    });
  }),

  // API Tokens endpoints
  http.get(`${API_BASE}/auth/tokens`, () => {
    return HttpResponse.json({
      data: mockApiTokens,
      total: mockApiTokens.length,
    });
  }),

  http.post(`${API_BASE}/auth/tokens`, async ({ request }) => {
    const body = await request.json() as any;
    const newToken = createMockApiToken({
      name: body.name,
      scopes: body.scopes,
    });
    return HttpResponse.json(
      { ...newToken, token: "qap_test_token_1234567890" },
      { status: 201 }
    );
  }),

  http.delete(`${API_BASE}/auth/tokens/:id`, ({ params }) => {
    return new HttpResponse(null, { status: 204 });
  }),

  // Git branch discovery
  http.post(`${API_BASE}/projects/branches`, async ({ request }) => {
    return HttpResponse.json({
      branches: ["main", "develop", "feature/test"],
      default_branch: "main",
    });
  }),
];
