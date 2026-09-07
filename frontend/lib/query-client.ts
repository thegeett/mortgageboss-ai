import { QueryClient } from "@tanstack/react-query";

import { revokePreviewsOnEviction } from "@/lib/api/inbound";
import { revokePageImagesOnEviction } from "@/lib/api/page-image";

export function makeQueryClient() {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000, // 1 minute
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
  // Tied to the CLIENT's life, not a component's. A page image is a blob url that
  // the cache outlives every component holding it, so the thing that frees it has
  // to outlive them too — subscribed from a hook, the listener was gone by the
  // time the eviction it was waiting for arrived.
  revokePageImagesOnEviction(client);
  // Triage thumbnails are blob urls with the same lifetime problem (LP-807), and a queue is a GRID
  // of them. Registered here for the same reason, beside the one it copies.
  revokePreviewsOnEviction(client);
  return client;
}
