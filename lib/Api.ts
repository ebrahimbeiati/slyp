// Real client for the Slyp API. No calculation happens here or anywhere
// else in the frontend - this only sends the file and returns exactly
// what the backend computed. See main.py for the request path.

import type { AnalysisResult } from "@/app/Types/Types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class AnalyseError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "AnalyseError";
    this.status = status;
  }
}

export async function analysePayslip(
  file: File,
  onlyJob: boolean | null,
): Promise<AnalysisResult> {
  const formData = new FormData();
  formData.append("file", file);
  if (onlyJob !== null) {
    formData.append("only_job", onlyJob ? "true" : "false");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/analyse`, {
      method: "POST",
      body: formData,
    });
  } catch {
    // Network failure, API unreachable, CORS rejection, etc. - the
    // request never got a response at all.
    throw new AnalyseError(
      0,
      "Couldn't reach the server. Check your connection and try again.",
    );
  }

  if (!response.ok) {
    let detail = "Something went wrong analysing this payslip. Please try again.";
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Response body wasn't JSON - keep the generic message rather than
      // showing raw response text to the user.
    }
    throw new AnalyseError(response.status, detail);
  }

  return (await response.json()) as AnalysisResult;
}
