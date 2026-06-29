import "@mantine/core/styles.css";
import "./styles.css";

import { MantineProvider } from "@mantine/core";
import { QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import { queryClient } from "./api/queryClient";
import { theme } from "./theme";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <MantineProvider theme={theme} defaultColorScheme="light">
        <App />
      </MantineProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
