export interface DiscardableResponse {
  body?: { cancel?: () => Promise<unknown> } | null;
}

export function discardResponseBody(
  resp: DiscardableResponse | null | undefined,
): void {
  try {
    const body = resp ? resp.body : null;
    if (body && typeof body.cancel === "function") {
      body.cancel().catch(() => {

      });
    }
  } catch {

  }
}
