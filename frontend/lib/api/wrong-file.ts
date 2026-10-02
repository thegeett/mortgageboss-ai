/**
 * LP-951 review — the server's wrong-file refusal (409, code `wrong_file`), for the doors that have
 * no review screen to show a warning on: attaching a PDF to a round, and merging a forwarded PDF into
 * one. The import door shows its warning on the review screen instead.
 */
import { getErrorMessage } from "@/lib/errors/api-error";
import { isAxiosError } from "axios";

/** True when the server refused because the sheet's borrower or loan number is not this file's. */
export function isWrongFileRefusal(error: unknown): boolean {
  if (!isAxiosError(error) || error.response?.status !== 409) return false;
  const data = error.response.data as { error?: { data?: { code?: unknown } } } | undefined;
  return data?.error?.data?.code === "wrong_file";
}

/**
 * Send once; on a wrong-file refusal, show her the server's sentence and send again with her
 * confirmation only if she says the sheet is this file's. Cancelling rethrows the refusal, so the
 * caller's error toast says why nothing was attached.
 */
export async function withWrongFileConfirmation<T>(
  send: (confirmWrongFile: boolean) => Promise<T>,
): Promise<T> {
  try {
    return await send(false);
  } catch (error) {
    if (
      !isWrongFileRefusal(error) ||
      !window.confirm(`${getErrorMessage(error)}\n\nIt is this file’s sheet — attach it anyway?`)
    ) {
      throw error;
    }
    return send(true);
  }
}
