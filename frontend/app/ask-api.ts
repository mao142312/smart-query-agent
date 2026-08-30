export interface AskResponse {
  request_id: string;
  answer: string;
  confidence: number;
  status: string;
  sql: string | null;
}

type Fetcher = typeof fetch;

export async function askQuestion(question: string, fetcher: Fetcher = fetch): Promise<AskResponse> {
  const response = await fetcher("/api/v1/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  const payload = await response.json() as AskResponse & { detail?: string };
  if (!response.ok) {
    throw new Error(payload.detail || `请求失败（HTTP ${response.status}）`);
  }
  return payload;
}
