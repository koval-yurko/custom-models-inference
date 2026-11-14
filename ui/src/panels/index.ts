import type { ComponentType } from "react";
import type { ModelConfig } from "../config";
import Llm from "./Llm";
import LlmRoutes from "./LlmRoutes";
import Tts from "./Tts";

// Model type (the `type` of the `ui` Terraform output) -> panel. Add a new type here (see the model-ui skill).
export const PANELS: Record<string, ComponentType<{ model: ModelConfig }>> = {
  llm: Llm,
  "llm-routes": LlmRoutes, // own JSON routes (LLM-B /extract, /generate)
  tts: Tts,
};
