import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./index.css";
import { ApiError } from "./lib/api";
import { navigate } from "./lib/router";
import { initTelegram, startParam } from "./lib/telegram";

initTelegram();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 30 * 60_000,
      // client errors (4xx) are final; network / 5xx retry with exponential backoff
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 3,
      retryDelay: (n) => Math.min(1000 * 2 ** n, 8000),
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
});

// Deep link: t.me/<bot>/<app>?startapp=article_123
const sp = startParam();
const deepLink = sp?.match(/^article_(\d+)$/);
if (deepLink && location.pathname === "/") navigate(`/article/${deepLink[1]}`, { replace: true });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
